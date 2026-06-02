from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pnn.asr.stream import StreamConfig, StreamingASR
from pnn.asr.transcriber import ASRTranscriber
from pnn.core.paths import (
    REMOTE_MODELS,
    is_english_only_model,
    list_available_models,
    model_info,
    resolve_local_model_path,
)

logger = logging.getLogger(__name__)

ModelSize = Literal["tiny", "base", "small", "medium", "large-v2", "large-v3"]
Device = Literal["auto", "cpu", "cuda"]

AVAILABLE_MODELS: list[str] = REMOTE_MODELS

AVAILABLE_LANGUAGES: list[dict[str, str]] = [
    {"code": "", "label": "自动检测"},
    {"code": "zh", "label": "中文"},
    {"code": "en", "label": "English"},
    {"code": "ja", "label": "日本語"},
]


@dataclass
class AsrConfig:
    model: str = "small"
    model_path: str | None = resolve_local_model_path("small") or resolve_local_model_path("tiny")
    device: Device = "cuda"
    compute_type: str = "default"
    language: str | None = "zh"
    silence_duration: float = 0.8
    partial_interval: float = 2.5
    energy_threshold: float | None = None


class AsrService:
    """管理 ASR 模型与流式识别会话。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config = AsrConfig()
        if self._config.model_path and resolve_local_model_path("small"):
            self._config.model = "small"
            self._config.model_path = resolve_local_model_path("small")
        self._sync_local_model_path()
        self._transcriber: ASRTranscriber | None = None
        self._stream: StreamingASR | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws_clients: set[Any] = set()
        self._status = "idle"
        self._loading = False
        self._starting = False
        self._last_error: str | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _sync_local_model_path(self) -> None:
        local_path = resolve_local_model_path(self._config.model)
        if local_path:
            self._config.model_path = local_path

    def _resolved_model_path(self) -> str | None:
        if self._config.model_path:
            from pathlib import Path

            path = Path(self._config.model_path)
            if path.is_dir() and (path / "model.bin").is_file():
                return str(path)
        return resolve_local_model_path(self._config.model)

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            self._sync_local_model_path()
            path = self._resolved_model_path()
            info = model_info(path)
            return asdict(self._config) | {
                "status": self._status,
                "loading": self._loading or self._starting,
                "resolved_device": self._transcriber.device if self._transcriber else None,
                "last_error": self._last_error,
                "model_multilingual": info["multilingual"],
                "model_warning": info["warning"],
                "active_threshold": (
                    self._stream.active_threshold if self._stream else self._config.energy_threshold
                ),
            }

    def list_models(self) -> dict[str, Any]:
        return {
            "models": list_available_models(),
            "languages": AVAILABLE_LANGUAGES,
        }

    def update_config(self, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            threshold_only = set(kwargs.keys()) <= {"energy_threshold"}
            if (self._stream is not None or self._starting) and not threshold_only:
                raise RuntimeError("请先停止识别再更换模型或配置")

            if "energy_threshold" in kwargs:
                value = kwargs["energy_threshold"]
                if value is not None and not (0.001 <= float(value) <= 0.8):
                    raise ValueError("energy_threshold 须在 0.001 ~ 0.8 之间")
                self._config.energy_threshold = float(value) if value is not None else None
                if self._stream is not None:
                    self._stream.set_energy_threshold(self._config.energy_threshold)
                if threshold_only:
                    return self.get_config()

            for key, value in kwargs.items():
                if key == "energy_threshold":
                    continue
                if not hasattr(self._config, key):
                    continue
                if key == "model":
                    if value not in AVAILABLE_MODELS:
                        raise ValueError(f"不支持的模型: {value}")
                    setattr(self._config, key, value)
                    local_path = resolve_local_model_path(value)
                    self._config.model_path = local_path
                    continue
                setattr(self._config, key, value)

            self._transcriber = None
            self._last_error = None
            return self.get_config()

    def _validate_language(self, model_path: str | None) -> None:
        language = self._config.language
        if language in ("zh", "ja", "ko") and model_path and is_english_only_model(model_path):
            raise RuntimeError(
                "当前模型是英文专用版（.en），无法识别中文。"
                "请从 HuggingFace 下载多语言版本 Systran/faster-whisper-small"
                "（注意：不要下载 faster-whisper-small.en），"
                "覆盖到 models/ASR/whisper/faster_whisper_small 后重启。"
            )

    def _ensure_transcriber(self) -> ASRTranscriber:
        with self._lock:
            if self._transcriber is not None:
                return self._transcriber
            self._loading = True

        try:
            model_path = self._resolved_model_path()
            if model_path:
                with self._lock:
                    self._config.model_path = model_path
            self._validate_language(model_path)
            logger.info(
                "Loading whisper model: %s path=%s device=%s language=%s",
                self._config.model,
                model_path or "(remote)",
                self._config.device,
                self._config.language or "auto",
            )
            transcriber = self._load_transcriber_with_timeout(model_path)
            transcriber = self._maybe_fallback_to_cpu(transcriber)
        except Exception as exc:
            raise RuntimeError(self._format_model_error(exc)) from exc
        finally:
            with self._lock:
                self._loading = False

        with self._lock:
            self._transcriber = transcriber
            return transcriber

    def _load_transcriber_with_timeout(
        self, model_path: str | None, timeout: float = 120.0
    ) -> ASRTranscriber:
        result: list[ASRTranscriber | BaseException] = [RuntimeError("模型加载未开始")]

        def worker() -> None:
            try:
                result[0] = ASRTranscriber(
                    model_size=self._config.model,  # type: ignore[arg-type]
                    device=self._config.device,
                    compute_type=self._config.compute_type,
                    model_path=model_path,
                )
            except BaseException as exc:
                result[0] = exc

        thread = threading.Thread(target=worker, name="asr-model-loader", daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise RuntimeError("模型加载超时，请将推理设备改为 CPU 后重试")
        if isinstance(result[0], BaseException):
            raise result[0]
        return result[0]

    @staticmethod
    def _format_model_error(exc: Exception) -> str:
        message = str(exc)
        if (
            "LocalEntryNotFoundError" in type(exc).__name__
            or "ConnectTimeout" in message
            or "Server disconnected" in message
        ):
            return (
                "模型加载失败：未找到本地模型或尝试联网下载失败。"
                "请确认 models/ASR/whisper 下存在 faster_whisper_tiny / faster_whisper_small，"
                "并重启后端（运行 scripts/start.bat）。"
            )
        return f"模型加载失败：{message}"

    @staticmethod
    def _maybe_fallback_to_cpu(transcriber: ASRTranscriber) -> ASRTranscriber:
        if transcriber.device != "cuda":
            return transcriber
        try:
            import numpy as np

            sample = np.zeros(16000, dtype=np.float32)
            segments, _ = transcriber.model.transcribe(sample, beam_size=1, vad_filter=False)
            list(segments)
            logger.info("CUDA 推理验证通过")
            return transcriber
        except Exception as exc:
            logger.warning("CUDA 推理失败 (%s)，回退到 CPU", exc)
        return ASRTranscriber(
            model_size=transcriber.model_size,  # type: ignore[arg-type]
            device="cpu",
            compute_type="int8",
            model_path=transcriber.model_path,
        )

    def register_ws(self, ws: Any) -> None:
        self._ws_clients.add(ws)

    def unregister_ws(self, ws: Any) -> None:
        self._ws_clients.discard(ws)

    def _broadcast(self, payload: dict[str, Any]) -> None:
        if self._loop is None:
            return
        dead: list[Any] = []
        for ws in list(self._ws_clients):
            try:
                asyncio.run_coroutine_threadsafe(ws.send_json(payload), self._loop)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ws_clients.discard(ws)

    def _set_status(self, status: str) -> None:
        with self._lock:
            self._status = status
        self._broadcast({"type": "status", "status": status})

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message
            self._status = "error"
        logger.error("ASR error: %s", message)
        self._broadcast({"type": "error", "message": message})
        self._broadcast({"type": "status", "status": "error"})

    def begin_start_stream(self) -> bool:
        """后台启动流式识别，立即返回。"""
        with self._lock:
            if self._stream is not None or self._starting:
                return False
            self._starting = True
            self._last_error = None

        self._set_status("loading")
        threading.Thread(
            target=self._start_stream_worker,
            name="asr-start-worker",
            daemon=True,
        ).start()
        return True

    def _start_stream_worker(self) -> None:
        try:
            transcriber = self._ensure_transcriber()

            def on_partial(text: str) -> None:
                self._broadcast({"type": "partial", "text": text})

            def on_final(text: str) -> None:
                logger.info("[完成] %s", text)
                self._broadcast({"type": "final", "text": text})

            def on_status(status: str) -> None:
                self._set_status(status)

            def on_level(energy: float, threshold: float, is_speech: bool) -> None:
                self._broadcast(
                    {
                        "type": "level",
                        "energy": round(energy, 4),
                        "threshold": round(threshold, 4),
                        "is_speech": is_speech,
                    }
                )

            stream = StreamingASR(
                transcriber.model,
                language=self._config.language or None,
                config=StreamConfig(
                    silence_duration=self._config.silence_duration,
                    partial_interval=self._config.partial_interval,
                    energy_threshold=self._config.energy_threshold,
                ),
                on_partial=on_partial,
                on_final=on_final,
                on_status=on_status,
                on_level=on_level,
                vad_filter=False,
            )

            with self._lock:
                self._stream = stream

            stream.start()
            self._set_status("listening")
        except Exception as exc:
            logger.exception("Failed to start stream")
            with self._lock:
                self._stream = None
            self._set_error(str(exc))
        finally:
            with self._lock:
                self._starting = False

    def stop_stream(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
            self._starting = False

        if stream is not None:
            stream.stop()
        self._set_status("idle")

    def transcribe_upload(self, file_path: str) -> dict[str, Any]:
        transcriber = self._ensure_transcriber()
        result = transcriber.transcribe_file(
            file_path,
            language=self._config.language or None,
        )
        return {
            "text": result.text,
            "language": result.language,
            "duration": result.duration,
        }


asr_service = AsrService()
