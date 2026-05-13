#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AV字幕 - 配置文件
请在下方填入你的 Azure Speech Service API 密钥
"""

# =============================================================================
# Azure Speech Service API 配置
# 获取方式: https://portal.azure.com → 创建 Speech Service 资源 → Keys and Endpoint
# =============================================================================

AZURE_SPEECH_KEY_1 = "YOUR_AZURE_SPEECH_KEY_1_HERE"
AZURE_SPEECH_KEY_2 = "YOUR_AZURE_SPEECH_KEY_2_HERE"
AZURE_SPEECH_KEY = AZURE_SPEECH_KEY_1
AZURE_SPEECH_REGION = "southeastasia"  # 修改为你的 Azure 区域
AZURE_SPEECH_ENDPOINT = "https://southeastasia.api.cognitive.microsoft.com/"

# =============================================================================
# 音频配置
# =============================================================================

AUDIO_CONFIG = {
    "TARGET_RATE": 16000,      # Azure 目标采样率
    "CHUNK_DURATION_MS": 100,  # 每次读取的时长(ms)，越小延迟越低
    "FORMAT": "paInt16",
    "CHANNELS": 1,
}

# =============================================================================
# 翻译配置
# =============================================================================

TRANSLATION_CONFIG = {
    "SOURCE_LANG": "ja-JP",
    "TARGET_LANG": "zh-Hans",
}

# =============================================================================
# UI 配置
# =============================================================================

UI_CONFIG = {
    "WINDOW_SIZE": "1300x1000",
    "DEFAULT_FONT_SIZE": "小",
    "DEFAULT_THEME": "light",
    "SOURCE_PANEL_WIDTH": 40,
    "CHINESE_PANEL_WIDTH": 60,
}

# =============================================================================
# 辅助函数
# =============================================================================

def switch_speech_key():
    """切换到备用 Azure Speech 密钥"""
    global AZURE_SPEECH_KEY
    if AZURE_SPEECH_KEY == AZURE_SPEECH_KEY_1:
        AZURE_SPEECH_KEY = AZURE_SPEECH_KEY_2
        print("🔄 已切换到备用 Azure Speech 密钥 (Key 2)")
    else:
        AZURE_SPEECH_KEY = AZURE_SPEECH_KEY_1
        print("🔄 已切换到主 Azure Speech 密钥 (Key 1)")
    return AZURE_SPEECH_KEY
