"""语音合成（TTS）模块 — 与 AI_assistant 相同的 Adapter + Manager 架构。"""

from pnn.tts.base import TTSAdapter
from pnn.tts.manager import TTSAdapterFactory, TTSManager
from pnn.tts.service import SUPPORTED_PROVIDERS, TtsConfig, TtsService, tts_service

__all__ = [
    "TTSAdapter",
    "TTSAdapterFactory",
    "TTSManager",
    "SUPPORTED_PROVIDERS",
    "TtsConfig",
    "TtsService",
    "tts_service",
]
