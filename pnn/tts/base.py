from __future__ import annotations

from abc import ABC, abstractmethod


class TTSAdapter(ABC):
    """TTS 适配器抽象基类（与 AI_assistant/sdk/adapters/tts.py 一致）。"""

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {}

    @abstractmethod
    def generate_speech(self, text, file_path=None, **kwargs):
        pass

    @abstractmethod
    def switch_model(self, model_info):
        pass
