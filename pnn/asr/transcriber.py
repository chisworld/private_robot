from __future__ import annotations

import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

import numpy as np
import sounddevice as sd

from pnn.asr.text_normalize import to_simplified_chinese
from pnn.core.cuda_runtime import setup_cuda_dlls

setup_cuda_dlls()

from faster_whisper import WhisperModel

ModelSize = Literal["tiny", "base", "small", "medium", "large-v2", "large-v3"]
Device = Literal["cpu", "cuda", "auto"]


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str
    language_probability: float
    duration: float
    segments: tuple[Segment, ...]


class ASRTranscriber:
    """基于 faster-whisper 的语音转文字封装。"""

    def __init__(
        self,
        model_size: ModelSize = "small",
        device: Device = "auto",
        compute_type: str = "default",
        download_root: str | Path | None = None,
        model_path: str | Path | None = None,
    ) -> None:
        resolved_device = self._resolve_device(device)
        resolved_compute = self._resolve_compute_type(compute_type, resolved_device)
        model_id = str(Path(model_path).expanduser().resolve()) if model_path else model_size
        self.model_size = model_size
        self.model_path = str(model_path) if model_path else None
        self.device = resolved_device
        self.compute_type = resolved_compute
        self._model = self._load_model(
            model_id,
            resolved_device,
            resolved_compute,
            download_root,
        )

    def _load_model(
        self,
        model_id: str,
        device: str,
        compute_type: str,
        download_root: str | Path | None,
    ) -> WhisperModel:
        kwargs: dict[str, object] = {
            "device": device,
            "compute_type": compute_type,
        }
        if download_root:
            kwargs["download_root"] = str(download_root)
        if Path(model_id).is_dir():
            kwargs["local_files_only"] = True
        try:
            return WhisperModel(model_id, **kwargs)
        except Exception:
            if device != "cuda":
                raise
            fallback: dict[str, object] = {
                "device": "cpu",
                "compute_type": "int8",
                "local_files_only": Path(model_id).is_dir(),
            }
            if download_root:
                fallback["download_root"] = str(download_root)
            return WhisperModel(model_id, **fallback)

    @property
    def model(self) -> WhisperModel:
        return self._model

    @staticmethod
    def _resolve_device(device: Device) -> str:
        if device == "cpu":
            return "cpu"
        if device == "cuda":
            return "cuda"
        # auto：优先 CPU，避免 CUDA 驱动/库不完整时崩溃
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda"
        except Exception:
            pass
        return "cpu"

    @staticmethod
    def _resolve_compute_type(compute_type: str, device: str) -> str:
        if compute_type and compute_type != "default":
            return compute_type
        return "float16" if device == "cuda" else "int8"

    def transcribe_file(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        task: Literal["transcribe", "translate"] = "transcribe",
        beam_size: int = 5,
        vad_filter: bool = True,
    ) -> TranscriptionResult:
        """识别音频文件，返回完整转写结果。"""
        path = Path(audio_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"音频文件不存在: {path}")

        segments_iter, info = self._model.transcribe(
            str(path),
            language=language,
            task=task,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )
        segments = tuple(self._collect_segments(segments_iter))
        text = to_simplified_chinese(
            "".join(segment.text for segment in segments).strip(), language
        )
        return TranscriptionResult(
            text=text,
            language=info.language,
            language_probability=info.language_probability,
            duration=info.duration,
            segments=segments,
        )

    def transcribe_microphone(
        self,
        duration: float = 5.0,
        *,
        samplerate: int = 16000,
        language: str | None = None,
        task: Literal["transcribe", "translate"] = "transcribe",
        beam_size: int = 5,
        vad_filter: bool = True,
    ) -> TranscriptionResult:
        """录制麦克风音频并转写。"""
        if duration <= 0:
            raise ValueError("duration 必须大于 0")

        frames = int(duration * samplerate)
        recording = sd.rec(frames, samplerate=samplerate, channels=1, dtype="float32")
        sd.wait()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            self._save_wav(tmp_path, recording, samplerate)
            return self.transcribe_file(
                tmp_path,
                language=language,
                task=task,
                beam_size=beam_size,
                vad_filter=vad_filter,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _collect_segments(segments_iter: Iterator) -> list[Segment]:
        return [
            Segment(start=segment.start, end=segment.end, text=segment.text)
            for segment in segments_iter
        ]

    @staticmethod
    def _save_wav(path: Path, audio: np.ndarray, samplerate: int) -> None:
        audio = np.squeeze(audio)
        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767).astype(np.int16)

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            wf.writeframes(pcm.tobytes())
