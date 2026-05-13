#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AV字幕
- Azure 一体化语音翻译（转录+翻译一步完成，延迟 ~0.3-0.5s）
- WASAPI Loopback + 麦克风双路混合（无需虚拟声卡）
- Tkinter 双面板实时显示日语原文和中文字幕
"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import threading
import time
import re
import os
import html
import tkinter as tk
from tkinter import scrolledtext, messagebox
from datetime import datetime

import numpy as np

try:
    import pyaudiowpatch as pyaudio
    HAS_LOOPBACK = True
    print("✅ pyaudiowpatch 已加载，支持系统音频捕获")
except ImportError:
    import pyaudio
    HAS_LOOPBACK = False
    print("⚠️ pyaudiowpatch 未安装，仅支持麦克风输入")

import azure.cognitiveservices.speech as speechsdk

from config import (
    AZURE_SPEECH_KEY,
    AZURE_SPEECH_REGION,
    AUDIO_CONFIG,
    TRANSLATION_CONFIG,
    UI_CONFIG,
)

# 音频常量
TARGET_RATE = AUDIO_CONFIG["TARGET_RATE"]
CHUNK_MS = AUDIO_CONFIG["CHUNK_DURATION_MS"]
TARGET_CHUNK = int(TARGET_RATE * CHUNK_MS / 1000)  # 每次推送的采样数


class AVSubtitleApp:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.mic_stream = None
        self.loopback_stream = None
        self.is_recording = False
        self.is_paused = False

        # Azure 对象（start 时创建）
        self.recognizer = None
        self.push_stream = None

        # 统计
        self.audio_push_count = 0
        self.recognition_count = 0
        self.translation_count = 0

        # 保存
        self.session_records = []
        self.session_start_time = None

        # 设备信息缓存
        self.loopback_info = None
        self.mic_id = None

        # 用户选择的设备（None = 自动）
        self.selected_mic_index = None
        self.selected_loopback_index = None

        # 字体配置
        self.font_sizes = {
            "最小": {"text": 8,  "button": 10, "label": 8,  "title": 10},
            "小":   {"text": 10, "button": 11, "label": 10, "title": 12},
            "中":   {"text": 12, "button": 13, "label": 12, "title": 14},
            "大":   {"text": 14, "button": 15, "label": 14, "title": 16},
            "最大": {"text": 16, "button": 17, "label": 16, "title": 18},
        }
        self.current_font_size = "小"

        # 主题
        self.is_dark_theme = False
        self.themes = {
            "light": {"bg": "white", "fg": "black", "insert": "black"},
            "dark":  {"bg": "#2b2b2b", "fg": "#ffffff", "insert": "#ffffff"},
        }

        self.setup_ui()

    # -----------------------------------------------------------------
    # 音频设备查找
    # -----------------------------------------------------------------

    def find_loopback_device(self):
        """找到 WASAPI Loopback 设备（系统音频输出）"""
        if not HAS_LOOPBACK:
            return None, None
        try:
            # 如果用户手动选择了设备
            if self.selected_loopback_index is not None:
                dev = self.audio.get_device_info_by_index(self.selected_loopback_index)
                print(f"✅ 系统音频 Loopback (手动): [{self.selected_loopback_index}] {dev['name']}  "
                      f"({int(dev['defaultSampleRate'])}Hz, {dev['maxInputChannels']}ch)")
                return self.selected_loopback_index, dev

            # 自动：找默认输出设备的 Loopback
            wasapi = self.audio.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out = self.audio.get_device_info_by_index(
                wasapi["defaultOutputDevice"]
            )
            for i in range(self.audio.get_device_count()):
                dev = self.audio.get_device_info_by_index(i)
                if (dev["name"].startswith(default_out["name"])
                        and dev.get("isLoopbackDevice", False)):
                    print(f"✅ 系统音频 Loopback: [{i}] {dev['name']}  "
                          f"({int(dev['defaultSampleRate'])}Hz, {dev['maxInputChannels']}ch)")
                    return i, dev
            print("⚠️ 未找到 Loopback 设备")
            return None, None
        except Exception as e:
            print(f"❌ 查找 Loopback 失败: {e}")
            return None, None

    def find_microphone(self):
        """找到真实麦克风"""
        # 如果用户手动选择了设备
        if self.selected_mic_index is not None:
            try:
                info = self.audio.get_device_info_by_index(self.selected_mic_index)
                print(f"✅ 麦克风 (手动): [{self.selected_mic_index}] {info['name']}  "
                      f"({int(info['defaultSampleRate'])}Hz)")
                return self.selected_mic_index
            except Exception:
                pass
        # 自动查找
        try:
            avoid = ['cable', 'virtual', 'output', 'vb-audio', 'voicemeeter', 'loopback']
            prefer = ['microphone', 'mic', '麦克风', 'array', 'built-in', 'input']
            candidates = []
            for i in range(self.audio.get_device_count()):
                try:
                    info = self.audio.get_device_info_by_index(i)
                    if info['maxInputChannels'] <= 0:
                        continue
                    name = info['name'].lower()
                    if any(k in name for k in avoid):
                        continue
                    score = sum(10 for k in prefer if k in name)
                    if info['defaultSampleRate'] == 16000:
                        score += 5
                    candidates.append((i, info, score))
                except Exception:
                    continue
            if candidates:
                best = max(candidates, key=lambda x: x[2])
                print(f"✅ 麦克风: [{best[0]}] {best[1]['name']}  "
                      f"({int(best[1]['defaultSampleRate'])}Hz)")
                return best[0]
            print("⚠️ 未找到麦克风，使用默认设备 0")
            return 0
        except Exception as e:
            print(f"❌ 查找麦克风失败: {e}")
            return 0

    def enumerate_microphones(self):
        """枚举所有可用麦克风，返回 [(display_name, device_index), ...]"""
        mics = [("自动选择", None)]
        avoid = ['loopback']
        for i in range(self.audio.get_device_count()):
            try:
                info = self.audio.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0 and not info.get('isLoopbackDevice', False):
                    name = info['name']
                    if not any(k in name.lower() for k in avoid):
                        rate = int(info['defaultSampleRate'])
                        mics.append((f"[{i}] {name} ({rate}Hz)", i))
            except Exception:
                continue
        return mics

    def enumerate_loopback_devices(self):
        """枚举所有可用 Loopback（外放源），返回 [(display_name, device_index), ...]"""
        devices = [("自动(跟随系统默认)", None)]
        if not HAS_LOOPBACK:
            return devices
        for i in range(self.audio.get_device_count()):
            try:
                info = self.audio.get_device_info_by_index(i)
                if info.get('isLoopbackDevice', False):
                    name = info['name'].replace(' [Loopback]', '')
                    rate = int(info['defaultSampleRate'])
                    ch = info['maxInputChannels']
                    devices.append((f"[{i}] {name} ({rate}Hz, {ch}ch)", i))
            except Exception:
                continue
        return devices

    def refresh_device_lists(self):
        """刷新设备列表下拉框"""
        # 刷新麦克风列表
        mics = self.enumerate_microphones()
        self._mic_devices = mics
        mic_names = [m[0] for m in mics]
        menu = self.mic_menu["menu"]
        menu.delete(0, "end")
        for name in mic_names:
            menu.add_command(label=name, command=lambda n=name: (self.mic_var.set(n), self.on_mic_selected()))

        # 刷新 Loopback 列表
        loops = self.enumerate_loopback_devices()
        self._loopback_devices = loops
        loop_names = [l[0] for l in loops]
        menu2 = self.loopback_menu["menu"]
        menu2.delete(0, "end")
        for name in loop_names:
            menu2.add_command(label=name, command=lambda n=name: (self.loopback_var.set(n), self.on_loopback_selected()))

        print(f"🔄 设备刷新: {len(mics)} 麦克风, {len(loops)} 外放源")

    def on_mic_selected(self, *args):
        """用户选择麦克风"""
        selected = self.mic_var.get()
        for name, idx in self._mic_devices:
            if name == selected:
                self.selected_mic_index = idx
                print(f"🎤 选择麦克风: {name}")
                break

    def on_loopback_selected(self, *args):
        """用户选择外放源"""
        selected = self.loopback_var.get()
        for name, idx in self._loopback_devices:
            if name == selected:
                self.selected_loopback_index = idx
                print(f"🔊 选择外放源: {name}")
                break

    # -----------------------------------------------------------------
    # 音频重采样 & 混合
    # -----------------------------------------------------------------

    @staticmethod
    def resample(data_int16, src_rate, dst_rate):
        """简单线性插值重采样"""
        if src_rate == dst_rate:
            return data_int16
        ratio = dst_rate / src_rate
        n_out = int(len(data_int16) * ratio)
        indices = np.linspace(0, len(data_int16) - 1, n_out)
        return np.interp(indices, np.arange(len(data_int16)), data_int16.astype(np.float32)).astype(np.int16)

    @staticmethod
    def to_mono(data_int16, channels):
        """多声道转单声道"""
        if channels <= 1:
            return data_int16
        reshaped = data_int16.reshape(-1, channels)
        return reshaped.mean(axis=1).astype(np.int16)

    # -----------------------------------------------------------------
    # 音频捕获线程
    # -----------------------------------------------------------------

    def _get_current_default_output_name(self):
        """获取当前系统默认输出设备名称"""
        try:
            wasapi = self.audio.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out = self.audio.get_device_info_by_index(wasapi["defaultOutputDevice"])
            return default_out["name"]
        except Exception:
            return ""

    def _open_loopback(self):
        """打开当前默认输出设备的 Loopback，返回 (stream, id, info, rate, ch, chunk) 或 None"""
        loop_id, loop_info = self.find_loopback_device()
        if loop_id is None:
            return None
        loop_rate = int(loop_info["defaultSampleRate"])
        loop_ch = loop_info["maxInputChannels"]
        loop_chunk = int(loop_rate * CHUNK_MS / 1000) * loop_ch
        try:
            stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=loop_ch,
                rate=loop_rate,
                input=True,
                frames_per_buffer=loop_chunk // loop_ch,
                input_device_index=loop_id,
            )
            dev_name = loop_info["name"].replace(" [Loopback]", "")
            print(f"✅ Loopback 已打开: {dev_name} ({loop_rate}Hz, {loop_ch}ch)")
            return stream, loop_id, loop_info, loop_rate, loop_ch, loop_chunk
        except Exception as e:
            print(f"❌ 打开 Loopback 失败: {e}")
            return None

    def audio_capture_thread(self):
        """双路捕获 → 混合 → 推送到 Azure（自动检测输出设备切换）"""
        print("🎧 音频捕获线程启动")

        # --- 打开 Loopback ---
        loopback_result = self._open_loopback()
        has_loopback = loopback_result is not None
        if has_loopback:
            self.loopback_stream, loop_id, loop_info, loop_rate, loop_ch, loop_chunk = loopback_result
            current_output_name = self._get_current_default_output_name()
        else:
            current_output_name = ""

        # --- 打开麦克风 ---
        self.mic_id = self.find_microphone()
        mic_rate = TARGET_RATE
        mic_chunk = TARGET_CHUNK
        has_mic = False
        try:
            self.mic_stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=mic_rate,
                input=True,
                frames_per_buffer=mic_chunk,
                input_device_index=self.mic_id,
            )
            has_mic = True
            print(f"✅ 麦克风音频流已打开 ({mic_rate}Hz, 1ch)")
        except Exception as e:
            print(f"❌ 打开麦克风失败: {e}")

        if not has_loopback and not has_mic:
            print("❌ 没有可用的音频输入！")
            self.root.after(0, lambda: messagebox.showerror("错误", "没有可用的音频输入设备！"))
            return

        source_desc = []
        if has_mic:
            source_desc.append("麦克风")
        if has_loopback:
            source_desc.append(f"系统音频({current_output_name[:15]})")
        self.root.after(0, lambda: self.status_label.config(
            text=f"状态: 正在识别... 音频源: {' + '.join(source_desc)}", fg="green"))

        # 设备切换检测计数器
        device_check_counter = 0
        DEVICE_CHECK_INTERVAL = 30  # 每 30 个 chunk (~3秒) 检测一次

        # --- 主循环 ---
        while self.is_recording:
            try:
                if self.is_paused:
                    silence = bytes(TARGET_CHUNK * 2)
                    self.push_stream.write(silence)
                    time.sleep(CHUNK_MS / 1000)
                    continue

                # --- 定期检测输出设备是否切换（仅在"自动"模式下） ---
                device_check_counter += 1
                if HAS_LOOPBACK and self.selected_loopback_index is None and device_check_counter >= DEVICE_CHECK_INTERVAL:
                    device_check_counter = 0
                    new_output_name = self._get_current_default_output_name()
                    if new_output_name and new_output_name != current_output_name:
                        print(f"🔄 检测到输出设备切换: {current_output_name} → {new_output_name}")
                        # 关闭旧 Loopback
                        if self.loopback_stream:
                            try:
                                self.loopback_stream.stop_stream()
                                self.loopback_stream.close()
                            except Exception:
                                pass
                            self.loopback_stream = None
                        # 打开新 Loopback
                        loopback_result = self._open_loopback()
                        if loopback_result:
                            self.loopback_stream, loop_id, loop_info, loop_rate, loop_ch, loop_chunk = loopback_result
                            has_loopback = True
                            current_output_name = new_output_name
                            desc = f"🔄 已切换到: {new_output_name[:20]}"
                            self.root.after(0, lambda d=desc: self.status_label.config(text=d, fg="green"))
                        else:
                            has_loopback = False
                            current_output_name = new_output_name

                # 读取麦克风
                mic_samples = np.zeros(TARGET_CHUNK, dtype=np.int16)
                if has_mic:
                    try:
                        raw = self.mic_stream.read(mic_chunk, exception_on_overflow=False)
                        mic_samples = np.frombuffer(raw, dtype=np.int16)
                    except Exception:
                        pass

                # 读取 Loopback
                loop_samples = np.zeros(TARGET_CHUNK, dtype=np.int16)
                if has_loopback:
                    try:
                        raw = self.loopback_stream.read(
                            loop_chunk // loop_ch, exception_on_overflow=False
                        )
                        arr = np.frombuffer(raw, dtype=np.int16)
                        arr = self.to_mono(arr, loop_ch)
                        loop_samples = self.resample(arr, loop_rate, TARGET_RATE)
                        if len(loop_samples) > TARGET_CHUNK:
                            loop_samples = loop_samples[:TARGET_CHUNK]
                        elif len(loop_samples) < TARGET_CHUNK:
                            loop_samples = np.pad(loop_samples, (0, TARGET_CHUNK - len(loop_samples)))
                    except Exception:
                        pass

                # 混合
                mixed = np.clip(
                    mic_samples.astype(np.int32) + loop_samples.astype(np.int32),
                    -32768, 32767
                ).astype(np.int16)

                # 推送到 Azure
                self.push_stream.write(mixed.tobytes())
                self.audio_push_count += 1

            except Exception as e:
                print(f"音频捕获错误: {e}")
                time.sleep(0.01)

        # 清理
        print("🎧 音频捕获线程结束")
        try:
            if self.mic_stream:
                self.mic_stream.stop_stream()
                self.mic_stream.close()
                self.mic_stream = None
        except Exception:
            pass
        try:
            if self.loopback_stream:
                self.loopback_stream.stop_stream()
                self.loopback_stream.close()
                self.loopback_stream = None
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Azure 事件回调
    # -----------------------------------------------------------------

    def on_recognizing(self, evt):
        """临时识别结果（显示在状态栏）"""
        if self.is_paused:
            return
        text = evt.result.text
        if not text:
            return
        # 获取临时翻译
        translations = evt.result.translations
        zh = translations.get("zh-Hans", "") if translations else ""
        display = text[:60] + "..." if len(text) > 60 else text
        self.root.after(0, lambda: self.status_label.config(
            text=f"🎤 {display}", fg="blue"))

    def on_recognized(self, evt):
        """最终识别结果 → 显示日语原文 + 中文翻译"""
        if self.is_paused:
            return
        reason = evt.result.reason
        if reason == speechsdk.ResultReason.TranslatedSpeech:
            en_text = evt.result.text.strip()
            translations = evt.result.translations
            zh_text = translations.get("zh-Hans", "").strip() if translations else ""

            if not en_text:
                return

            self.recognition_count += 1

            # 后处理
            en_text = self.clean_text(en_text)
            zh_text = self.postprocess_translation(zh_text)

            if en_text and zh_text:
                self.translation_count += 1
                self.save_record(en_text, zh_text)

                # 显示
                self.root.after(0, lambda e=en_text: self._append_english(e))
                self.root.after(0, lambda z=zh_text: self._append_chinese(z))
                self.root.after(0, lambda: self.status_label.config(
                    text="状态: 识别中... (Azure Speech Translation)", fg="green"))

                print(f"🟢 JA: {en_text}")
                print(f"🟢 ZH: {zh_text}")

        elif reason == speechsdk.ResultReason.NoMatch:
            pass  # 没有匹配，正常

    def on_canceled(self, evt):
        """识别取消/出错"""
        cancellation = evt.result.cancellation_details
        print(f"❌ Azure 取消: {cancellation.reason}")
        if cancellation.reason == speechsdk.CancellationReason.Error:
            print(f"   错误码: {cancellation.error_code}")
            print(f"   详情: {cancellation.error_details}")
            self.root.after(0, lambda: self.status_label.config(
                text=f"❌ Azure 错误: {cancellation.error_details[:80]}", fg="red"))

    def on_session_started(self, evt):
        print("✅ Azure 会话已建立")

    def on_session_stopped(self, evt):
        print("⏹ Azure 会话已结束")

    # -----------------------------------------------------------------
    # 文本处理
    # -----------------------------------------------------------------

    def _append_english(self, text):
        self.english_text.insert(tk.END, f"{text}\n")
        self.english_text.see(tk.END)

    def _append_chinese(self, text):
        self.chinese_text.insert(tk.END, f"{text}\n")
        self.chinese_text.see(tk.END)

    @staticmethod
    def clean_text(text):
        if not text:
            return text
        text = re.sub(r'\s+', ' ', text.strip())
        words = text.split()
        cleaned = []
        prev = ""
        for w in words:
            if w.lower() != prev.lower():
                cleaned.append(w)
                prev = w
        return " ".join(cleaned)

    @staticmethod
    def postprocess_translation(text):
        if not text:
            return text
        text = html.unescape(text)
        for old, new in [('，，', '，'), ('。。', '。'), ('？？', '？'),
                         ('！！', '！'), (' ，', '，'), (' 。', '。')]:
            text = text.replace(old, new)
        return text.strip()

    def save_record(self, en, zh):
        ts = datetime.now().strftime("%H:%M:%S")
        self.session_records.append({"timestamp": ts, "original": en, "translated": zh})

    # -----------------------------------------------------------------
    # 录制控制
    # -----------------------------------------------------------------

    def start_recording(self):
        try:
            mic_desc = self.mic_var.get()
            loop_desc = self.loopback_var.get()
            result = messagebox.askyesno(
                "确认",
                "🎤 开始 Azure Speech Translation 实时翻译？\n\n"
                f"麦克风: {mic_desc}\n"
                f"外放源: {loop_desc}\n"
                "引擎: Azure Speech Translation (一体化低延迟)\n"
                "源语言: 日语 → 目标语言: 中文\n\n"
                "这将产生 Azure API 费用。"
            )
            if not result:
                return

            self.session_start_time = datetime.now()
            self.session_records.clear()
            self.audio_push_count = 0
            self.recognition_count = 0
            self.translation_count = 0
            self.is_paused = False

            # 创建 Azure 翻译识别器
            speech_config = speechsdk.translation.SpeechTranslationConfig(
                subscription=AZURE_SPEECH_KEY,
                region=AZURE_SPEECH_REGION,
            )
            speech_config.speech_recognition_language = TRANSLATION_CONFIG["SOURCE_LANG"]
            speech_config.add_target_language(TRANSLATION_CONFIG["TARGET_LANG"])
            # 降低延迟
            speech_config.set_property(
                speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "15000"
            )
            speech_config.set_property(
                speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "5000"
            )

            # 创建 PushAudioInputStream
            stream_format = speechsdk.audio.AudioStreamFormat(
                samples_per_second=TARGET_RATE,
                bits_per_sample=16,
                channels=1,
            )
            self.push_stream = speechsdk.audio.PushAudioInputStream(
                stream_format=stream_format
            )
            audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)

            # 创建识别器
            self.recognizer = speechsdk.translation.TranslationRecognizer(
                translation_config=speech_config,
                audio_config=audio_config,
            )

            # 注册回调
            self.recognizer.recognizing.connect(self.on_recognizing)
            self.recognizer.recognized.connect(self.on_recognized)
            self.recognizer.canceled.connect(self.on_canceled)
            self.recognizer.session_started.connect(self.on_session_started)
            self.recognizer.session_stopped.connect(self.on_session_stopped)

            # 开始连续识别
            self.recognizer.start_continuous_recognition()

            # 标记录制
            self.is_recording = True

            # 启动音频捕获线程
            self.capture_thread = threading.Thread(target=self.audio_capture_thread, daemon=True)
            self.capture_thread.start()

            # 更新 UI
            self.start_button.config(state=tk.DISABLED)
            self.pause_button.config(state=tk.NORMAL)
            self.resume_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.mic_menu.config(state=tk.DISABLED)
            self.loopback_menu.config(state=tk.DISABLED)
            self.status_label.config(text="状态: 正在连接 Azure...", fg="orange")

            print("🎤 开始 Azure Speech Translation (双路混合)")

        except Exception as e:
            print(f"启动错误: {e}")
            import traceback
            traceback.print_exc()
            messagebox.showerror("错误", f"启动失败: {e}")

    def pause_recording(self):
        self.is_paused = True
        self.pause_button.config(state=tk.DISABLED)
        self.resume_button.config(state=tk.NORMAL)
        self.status_label.config(text="状态: 已暂停 (保持连接)", fg="orange")
        print("⏸️ 已暂停")

    def resume_recording(self):
        self.is_paused = False
        self.pause_button.config(state=tk.NORMAL)
        self.resume_button.config(state=tk.DISABLED)
        self.status_label.config(text="状态: 继续识别...", fg="green")
        print("▶️ 已继续")

    def stop_recording(self):
        print("🛑 正在停止...")
        self.status_label.config(text="状态: 正在停止...", fg="orange")
        self.is_recording = False
        self.is_paused = False

        # 停止 Azure 识别
        if self.recognizer:
            try:
                self.recognizer.stop_continuous_recognition()
            except Exception as e:
                print(f"停止识别器错误: {e}")

        # 关闭推送流
        if self.push_stream:
            try:
                self.push_stream.close()
            except Exception as e:
                print(f"关闭推送流错误: {e}")

        # 等待捕获线程结束
        if hasattr(self, 'capture_thread') and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=3)

        # UI
        self.start_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
        self.resume_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        self.mic_menu.config(state=tk.NORMAL)
        self.loopback_menu.config(state=tk.NORMAL)
        self.status_label.config(text="状态: 已停止 (可重新开始)", fg="gray")

        # 自动保存
        if self.session_records:
            self.auto_save_to_file()
            fname = self._record_filename()
            messagebox.showinfo(
                "会话结束",
                f"本次会话统计:\n"
                f"📤 音频推送: {self.audio_push_count}\n"
                f"📥 识别结果: {self.recognition_count}\n"
                f"🌐 翻译记录: {self.translation_count}\n"
                f"🔧 引擎: Azure Speech Translation\n"
                f"💾 已保存到: {fname}"
            )

        print("⏹️ 已停止")

    # -----------------------------------------------------------------
    # 保存记录
    # -----------------------------------------------------------------

    def _record_filename(self):
        ts = self.session_start_time.strftime('%Y%m%d_%H%M%S') if self.session_start_time else datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"字幕记录_{ts}.txt"

    def auto_save_to_file(self):
        try:
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), self._record_filename())
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("🎬 AV字幕 翻译记录\n")
                f.write("=" * 50 + "\n")
                f.write(f"会话时间: {self.session_start_time.strftime('%Y-%m-%d %H:%M:%S') if self.session_start_time else '未知'}\n")
                f.write(f"翻译引擎: Azure Speech Translation (一体化)\n")
                f.write(f"音频源: 麦克风 + 系统音频 (WASAPI Loopback)\n")
                f.write(f"总翻译: {self.translation_count} 条\n")
                f.write("=" * 50 + "\n\n")
                for i, r in enumerate(self.session_records, 1):
                    f.write(f"[{r['timestamp']}] 记录 {i:03d}\n")
                    f.write(f"  JA: {r['original']}\n")
                    f.write(f"  ZH: {r['translated']}\n\n")
            print(f"💾 已保存: {filepath}")
        except Exception as e:
            print(f"保存错误: {e}")

    def manual_save_records(self):
        if not self.session_records:
            messagebox.showinfo("提示", "暂无翻译记录")
            return
        self.auto_save_to_file()
        messagebox.showinfo("保存成功", f"已保存 {len(self.session_records)} 条记录\n文件: {self._record_filename()}")

    def view_translation_records(self):
        if not self.session_records:
            messagebox.showinfo("提示", "暂无翻译记录")
            return
        win = tk.Toplevel(self.root)
        win.title("字幕记录 (AV字幕)")
        win.geometry("800x600")
        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("SimHei", 11))
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        txt.insert(tk.END, f"共 {len(self.session_records)} 条记录\n{'='*60}\n\n")
        for i, r in enumerate(self.session_records, 1):
            txt.insert(tk.END, f"[{r['timestamp']}] 记录 {i:03d}\n")
            txt.insert(tk.END, f"  JA: {r['original']}\n")
            txt.insert(tk.END, f"  ZH: {r['translated']}\n")
            txt.insert(tk.END, "-" * 40 + "\n\n")
        txt.config(state=tk.DISABLED)
        tk.Button(win, text="关闭", command=win.destroy, bg="lightcoral", font=("Arial", 12), width=12).pack(pady=10)

    # -----------------------------------------------------------------
    # UI 操作
    # -----------------------------------------------------------------

    def clear_text(self):
        if messagebox.askyesno("确认", "清空所有文本？"):
            self.english_text.delete(1.0, tk.END)
            self.chinese_text.delete(1.0, tk.END)
            self.status_label.config(text="文本已清空")

    def change_font_size(self):
        self.current_font_size = self.font_var.get()
        f = self.font_sizes[self.current_font_size]
        self.english_text.config(font=("Yu Gothic UI", f["text"]))
        self.chinese_text.config(font=("SimHei", f["text"]))
        for btn in [self.start_button, self.pause_button, self.resume_button, self.stop_button]:
            btn.config(font=("Arial", f["button"], "bold"))
        for btn in [self.clear_button, self.view_records_button, self.save_button]:
            btn.config(font=("Arial", f["button"]))
        self.status_label.config(font=("Arial", f["label"]))
        self.stats_label.config(font=("Arial", f["label"]))
        self.english_title.config(font=("Arial", f["title"], "bold"))
        self.chinese_title.config(font=("Arial", f["title"], "bold"))

    def toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        t = self.themes["dark" if self.is_dark_theme else "light"]
        for widget in [self.english_text, self.chinese_text]:
            widget.config(bg=t["bg"], fg=t["fg"], insertbackground=t["insert"])
        if self.is_dark_theme:
            self.theme_button.config(text="☀️ 亮色", bg="lightblue")
        else:
            self.theme_button.config(text="🌓 反色", bg="lightyellow")

    def update_stats(self):
        self.stats_label.config(
            text=f"音频推送: {self.audio_push_count} | 识别: {self.recognition_count} | 翻译: {self.translation_count}"
        )
        self.root.after(1000, self.update_stats)

    # -----------------------------------------------------------------
    # UI 构建
    # -----------------------------------------------------------------

    def setup_ui(self):
        self.root = tk.Tk()
        self.root.title("AV字幕 - 日语转中文字幕")
        self.root.geometry(UI_CONFIG["WINDOW_SIZE"])

        # --- 设置区 ---
        settings = tk.Frame(self.root, relief=tk.RAISED, bd=1, bg="lightgray")
        settings.pack(fill=tk.X, padx=10, pady=5)

        # 字体大小
        font_frame = tk.Frame(settings, bg="lightgray")
        font_frame.pack(side=tk.LEFT, padx=10, pady=5)
        tk.Label(font_frame, text="字体:", font=("Arial", 10), bg="lightgray").pack(side=tk.LEFT)
        self.font_var = tk.StringVar(value=self.current_font_size)
        for s in ["最小", "小", "中", "大", "最大"]:
            tk.Radiobutton(font_frame, text=s, variable=self.font_var, value=s,
                           command=self.change_font_size, font=("Arial", 9), bg="lightgray").pack(side=tk.LEFT, padx=2)

        # 主题
        theme_frame = tk.Frame(settings, bg="lightgray")
        theme_frame.pack(side=tk.LEFT, padx=20, pady=5)
        self.theme_button = tk.Button(theme_frame, text="🌓 反色", command=self.toggle_theme,
                                      bg="lightyellow", font=("Arial", 10, "bold"), width=8, relief=tk.RAISED, bd=2)
        self.theme_button.pack(side=tk.LEFT, padx=5)

        # 引擎标签
        tk.Label(settings, text="AV字幕: 日语 → 中文 (Azure Speech Translation)",
                 font=("Arial", 9), bg="lightgray", fg="green").pack(side=tk.RIGHT, padx=10)

        # --- 音频设备选择区 ---
        device_frame = tk.Frame(self.root, relief=tk.GROOVE, bd=1, bg="#f0f0f0")
        device_frame.pack(fill=tk.X, padx=10, pady=3)

        # 麦克风选择
        mic_frame = tk.Frame(device_frame, bg="#f0f0f0")
        mic_frame.pack(side=tk.LEFT, padx=10, pady=4)
        tk.Label(mic_frame, text="🎤 麦克风:", font=("Arial", 9), bg="#f0f0f0").pack(side=tk.LEFT)
        self._mic_devices = self.enumerate_microphones()
        self.mic_var = tk.StringVar(value=self._mic_devices[0][0])
        self.mic_menu = tk.OptionMenu(mic_frame, self.mic_var,
                                       *[m[0] for m in self._mic_devices],
                                       command=self.on_mic_selected)
        self.mic_menu.config(font=("Arial", 8), width=30)
        self.mic_menu.pack(side=tk.LEFT, padx=5)

        # 外放源选择
        loop_frame = tk.Frame(device_frame, bg="#f0f0f0")
        loop_frame.pack(side=tk.LEFT, padx=10, pady=4)
        tk.Label(loop_frame, text="🔊 外放源:", font=("Arial", 9), bg="#f0f0f0").pack(side=tk.LEFT)
        self._loopback_devices = self.enumerate_loopback_devices()
        self.loopback_var = tk.StringVar(value=self._loopback_devices[0][0])
        self.loopback_menu = tk.OptionMenu(loop_frame, self.loopback_var,
                                            *[l[0] for l in self._loopback_devices],
                                            command=self.on_loopback_selected)
        self.loopback_menu.config(font=("Arial", 8), width=30)
        self.loopback_menu.pack(side=tk.LEFT, padx=5)

        # 刷新按钮
        refresh_btn = tk.Button(device_frame, text="🔄 刷新", command=self.refresh_device_lists,
                                bg="#e0e0e0", font=("Arial", 9), width=6, relief=tk.RAISED, bd=1)
        refresh_btn.pack(side=tk.LEFT, padx=10, pady=4)

        # --- 按钮区 ---
        ctrl = tk.Frame(self.root)
        ctrl.pack(pady=10)

        f = self.font_sizes[self.current_font_size]
        self.start_button = tk.Button(ctrl, text="🎤 开始识别", command=self.start_recording,
                                       bg="lightgreen", font=("Arial", f["button"], "bold"), width=10, height=2)
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.pause_button = tk.Button(ctrl, text="⏸️ 暂停", command=self.pause_recording,
                                       state=tk.DISABLED, bg="orange", font=("Arial", f["button"], "bold"), width=8, height=2)
        self.pause_button.pack(side=tk.LEFT, padx=5)

        self.resume_button = tk.Button(ctrl, text="▶️ 继续", command=self.resume_recording,
                                        state=tk.DISABLED, bg="lightblue", font=("Arial", f["button"], "bold"), width=8, height=2)
        self.resume_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = tk.Button(ctrl, text="⏹ 停止", command=self.stop_recording,
                                      state=tk.DISABLED, bg="lightcoral", font=("Arial", f["button"], "bold"), width=8, height=2)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = tk.Button(ctrl, text="🗑️ 清空", command=self.clear_text,
                                       bg="lightblue", font=("Arial", f["button"]), width=8, height=2)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        self.view_records_button = tk.Button(ctrl, text="📋 查看记录", command=self.view_translation_records,
                                              bg="lightyellow", font=("Arial", f["button"]), width=10, height=2)
        self.view_records_button.pack(side=tk.LEFT, padx=5)

        self.save_button = tk.Button(ctrl, text="💾 保存记录", command=self.manual_save_records,
                                      bg="lightgreen", font=("Arial", f["button"]), width=10, height=2)
        self.save_button.pack(side=tk.LEFT, padx=5)

        # --- 状态 ---
        self.status_label = tk.Label(self.root, text="状态: 就绪 (AV字幕)",
                                      fg="blue", font=("Arial", f["label"]))
        self.status_label.pack(pady=5)

        self.stats_label = tk.Label(self.root, text="音频推送: 0 | 识别: 0 | 翻译: 0",
                                     font=("Arial", f["label"]))
        self.stats_label.pack(pady=2)

        # --- 内容区 ---
        content = tk.Frame(self.root)
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        ew = UI_CONFIG["SOURCE_PANEL_WIDTH"]
        cw = UI_CONFIG["CHINESE_PANEL_WIDTH"]
        content.grid_columnconfigure(0, weight=ew)
        content.grid_columnconfigure(1, weight=cw)
        content.grid_rowconfigure(0, weight=1)

        theme = self.themes["light"]

        # 左 - 日语原文
        left = tk.Frame(content)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.english_title = tk.Label(left, text=f"🇯🇵 日语识别 ({ew}%)",
                                       font=("Arial", f["title"], "bold"))
        self.english_title.pack(pady=5)
        self.english_text = scrolledtext.ScrolledText(left, wrap=tk.WORD,
                                                       font=("Yu Gothic UI", f["text"]), height=16,
                                                       bg=theme["bg"], fg=theme["fg"], insertbackground=theme["insert"])
        self.english_text.pack(fill=tk.BOTH, expand=True)

        # 右 - 中文
        right = tk.Frame(content)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.chinese_title = tk.Label(right, text=f"🇨🇳 中文翻译 ({cw}%) - Azure",
                                       font=("Arial", f["title"], "bold"))
        self.chinese_title.pack(pady=5)
        self.chinese_text = scrolledtext.ScrolledText(right, wrap=tk.WORD,
                                                       font=("SimHei", f["text"]), height=16,
                                                       bg=theme["bg"], fg=theme["fg"], insertbackground=theme["insert"])
        self.chinese_text.pack(fill=tk.BOTH, expand=True)

        self.update_stats()

    # -----------------------------------------------------------------
    # 运行 & 关闭
    # -----------------------------------------------------------------

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        print("🚀 AV字幕 启动")
        print(f"   引擎: Azure Speech Translation (一体化)")
        print(f"   语言: 日语 → 中文")
        print(f"   音频: 麦克风 + 系统音频 WASAPI Loopback")
        print(f"   Loopback 支持: {'✅ 是' if HAS_LOOPBACK else '❌ 否'}")
        print("=" * 60)
        self.root.mainloop()

    def on_closing(self):
        if self.is_recording:
            self.is_recording = False
            self.is_paused = False
            if self.recognizer:
                try:
                    self.recognizer.stop_continuous_recognition()
                except Exception:
                    pass
            if self.push_stream:
                try:
                    self.push_stream.close()
                except Exception:
                    pass
            if hasattr(self, 'capture_thread') and self.capture_thread.is_alive():
                self.capture_thread.join(timeout=2)

        if self.session_records:
            self.auto_save_to_file()

        try:
            self.audio.terminate()
        except Exception:
            pass

        self.root.after(300, self.root.destroy)


def main():
    print("🎬 AV字幕")
    print("   日语转中文字幕 + WASAPI Loopback 系统音频")
    print("   无需虚拟声卡，延迟 ~0.3-0.5s")
    print("=" * 60)
    try:
        app = AVSubtitleApp()
        app.run()
    except Exception as e:
        print(f"启动错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
