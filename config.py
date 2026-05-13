#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AV字幕 - 配置文件
请在下方填入你的 Azure Speech、Deepgram 和 Google Translate API 密钥。
"""

# =============================================================================
# API 配置
# =============================================================================

DEEPGRAM_API_KEY = "YOUR_DEEPGRAM_API_KEY_HERE"
GOOGLE_TRANSLATE_API_KEY = "YOUR_GOOGLE_TRANSLATE_API_KEY_HERE"
AZURE_SPEECH_KEY_1 = "YOUR_AZURE_SPEECH_KEY_1_HERE"
AZURE_SPEECH_KEY_2 = "YOUR_AZURE_SPEECH_KEY_2_HERE"
AZURE_SPEECH_KEY = AZURE_SPEECH_KEY_1
AZURE_SPEECH_REGION = "southeastasia"
AZURE_SPEECH_ENDPOINT = "https://southeastasia.api.cognitive.microsoft.com/"
SUBTITLE_ENGINE = "azure"  # azure 或 deepgram_google

# =============================================================================
# 音频配置
# =============================================================================

AUDIO_CONFIG = {
    "TARGET_RATE": 16000,      # 实时识别目标采样率
    "CHUNK_DURATION_MS": 100,  # 每次读取的时长(ms)，越小延迟越低
    "FORMAT": "paInt16",
    "CHANNELS": 1,
}

# =============================================================================
# 翻译配置
# =============================================================================

TRANSLATION_CONFIG = {
    "SOURCE_LANG": "ja",
    "TARGET_LANG": "zh-CN",
}

AZURE_TRANSLATION_CONFIG = {
    "SOURCE_LANG": "ja-JP",
    "TARGET_LANG": "zh-Hans",
}

DEEPGRAM_CONFIG = {
    "MODEL": "nova-3",
    "ENDPOINTING_MS": 300,
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

try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
