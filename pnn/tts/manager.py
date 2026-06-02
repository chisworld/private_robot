from __future__ import annotations

import logging
import threading
from pathlib import Path

from pnn.core.audio_cache import (
    MAX_AUDIO_CACHE_FILES,
    ensure_audio_cache_dir,
    prune_audio_cache,
)
from pnn.tts.adapters import (
    CosyVoiceAdapter,
    GenieTTSAdapter,
    GPTSoVitsAdapter,
    IndexTTSAdapter,
)
from pnn.tts.base import TTSAdapter
from pnn.tts.probe import probe_http_server

logger = logging.getLogger(__name__)


class TTSAdapterFactory:
    """TTS 适配器工厂（与 AI_assistant/tts/tts_manager.py 一致）。"""

    _adapters = {
        "gpt-sovits": GPTSoVitsAdapter,
        "genie-tts": GenieTTSAdapter,
        "index-tts": IndexTTSAdapter,
        "cosyvoice": CosyVoiceAdapter,
    }

    @staticmethod
    def create_adapter(adapter_name: str, **kwargs) -> TTSAdapter:
        adapter_class = TTSAdapterFactory._adapters.get(adapter_name.lower())
        if not adapter_class:
            supported = list(TTSAdapterFactory._adapters.keys())
            raise ValueError(f"Unsupported TTS adapter: '{adapter_name}'. Supported: {supported}")
        try:
            return adapter_class(**kwargs)
        except TypeError as exc:
            logger.error("Error creating adapter '%s'. Check required arguments.", adapter_name)
            raise exc


class TTSManager:
    """TTS 管理器（与 AI_assistant/tts/tts_manager.py 核心逻辑一致）。"""

    def __init__(self, tts_server_url: str = "http://127.0.0.1:9880/"):
        self.audio_cache_dir = ensure_audio_cache_dir()
        self.tts_server_url = tts_server_url.rstrip("/") + "/"
        self.cache_num = MAX_AUDIO_CACHE_FILES
        self.index = 0
        self.tts_adapter: TTSAdapter | None = None
        self.voice_language = "ja"
        self._lock = threading.RLock()

    def set_tts_adapter(self, adapter: TTSAdapter) -> None:
        with self._lock:
            self.tts_adapter = adapter

    def set_language(self, language: str) -> None:
        with self._lock:
            self.voice_language = language

    def generate_tts(
        self,
        text,
        *,
        ref_audio_path=None,
        prompt_text=None,
        prompt_lang=None,
        character_name=None,
        speed_factor=None,
    ):
        with self._lock:
            if self.tts_adapter is None:
                raise RuntimeError("TTS 适配器未设置")

            if not ref_audio_path:
                logger.warning("No reference audio provided")
                return ""

            file_path = str(self.audio_cache_dir / f"{self.index % self.cache_num}.wav")
            self.index += 1

            result = self.tts_adapter.generate_speech(
                text=text,
                file_path=file_path,
                ref_audio_path=ref_audio_path,
                prompt_text=prompt_text,
                prompt_lang=prompt_lang,
                text_lang=self.voice_language,
                character_name=character_name,
                speed_factor=speed_factor,
            )
            prune_audio_cache(self.audio_cache_dir)
            return result

    def switch_model(self, model_info) -> None:
        with self._lock:
            if self.tts_adapter is None:
                raise RuntimeError("TTS 适配器未设置")
            if model_info is None:
                logger.warning("No model info provided, cannot switch model.")
                return
            self.tts_adapter.switch_model(model_info)

    def is_server_alive(self) -> bool:
        with self._lock:
            adapter = self.tts_adapter
            if adapter is None:
                return False
            url = getattr(adapter, "tts_server_url", None) or getattr(
                adapter, "index_server_url", None
            )
            if not url:
                return False
            return probe_http_server(url)

    def start_server(self, *, force_restart: bool = False) -> None:
        with self._lock:
            adapter = self.tts_adapter
            if adapter is None:
                raise RuntimeError("TTS 适配器未设置")
            starter = getattr(adapter, "_start_server_process", None)
            if callable(starter):
                starter(force_restart=force_restart)

    def shutdown(self) -> None:
        with self._lock:
            if self.tts_adapter is not None and hasattr(self.tts_adapter, "stop_server"):
                self.tts_adapter.stop_server()
            self.tts_adapter = None
