# AV字幕

日语转中文字幕工具。使用 Azure Speech Translation 进行实时语音识别和翻译，支持同时捕获麦克风与系统播放声音。

## 功能

- 日语语音识别并实时翻译为简体中文
- WASAPI Loopback 捕获系统音频，无需虚拟声卡
- 可手动选择麦克风和外放音频源
- 双面板显示日语原文和中文字幕
- 暂停、继续、停止、清空、查看记录、保存记录
- 自动保存字幕记录到本地文本文件

## 安装

```bash
pip install -r requirements.txt
```

## 配置

在 Azure Portal 创建 Speech Service 资源后，把 API Key 和 Region 填入 `config.py`：

```python
AZURE_SPEECH_KEY_1 = "your_key_here"
AZURE_SPEECH_REGION = "southeastasia"
```

默认语言配置：

```python
TRANSLATION_CONFIG = {
    "SOURCE_LANG": "ja-JP",
    "TARGET_LANG": "zh-Hans",
}
```

## 运行

```bash
python av字幕.py
```

## 说明

本仓库只保留字幕识别、翻译、音频捕获和记录保存功能。
