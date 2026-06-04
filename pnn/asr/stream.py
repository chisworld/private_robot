from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Literal

import numpy as np

from pnn.asr.hallucination import audio_loud_enough, filter_transcript
from pnn.asr.text_normalize import to_simplified_chinese

if TYPE_CHECKING:
    from faster_whisper import WhisperModel
    import sounddevice as sd

PartialCallback = Callable[[str], None]
FinalCallback = Callable[[str], None]
StatusCallback = Callable[[str], None]
LevelCallback = Callable[[float, float, bool], None]

_logger = logging.getLogger(__name__)


@dataclass
class StreamConfig:
    samplerate: int = 16000
    block_duration: float = 0.05
    silence_duration: float = 0.8
    min_speech_duration: float = 0.7
    partial_interval: float = 2.5
    partial_window_seconds: float = 3.0
    max_utterance_seconds: float = 12.0
    energy_threshold: float | None = None
    energy_multiplier: float = 2.5
    speech_start_multiplier: float = 1.0
    min_energy_threshold: float = 0.008
    min_transcribe_rms: float = 0.006
    level_smoothing: float = 0.35
    calibration_blocks: int = 20
    max_buffer_seconds: float = 15.0
    audio_queue_size: int = 64


@dataclass
class _TranscribeJob:
    audio: np.ndarray
    kind: Literal["partial", "final"]


class StreamingASR:
    """麦克风实时流式识别：边说边出 partial，停顿后输出 final。"""

    def __init__(
        self,
        model: WhisperModel,
        *,
        language: str | None = None,
        task: Literal["transcribe", "translate"] = "transcribe",
        config: StreamConfig | None = None,
        on_partial: PartialCallback | None = None,
        on_final: FinalCallback | None = None,
        on_status: StatusCallback | None = None,
        on_level: LevelCallback | None = None,
        input_device: int | None = None,
        beam_size: int = 1,
        vad_filter: bool = False,
    ) -> None:
        self._model = model
        self.language = language
        self.task = task
        self.config = config or StreamConfig()
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_status = on_status
        self.on_level = on_level
        self.input_device = input_device
        self.beam_size = beam_size
        self.vad_filter = vad_filter

        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue(
            maxsize=self.config.audio_queue_size,
        )
        self._transcribe_queue: queue.Queue[_TranscribeJob | None] = queue.Queue(maxsize=1)
        self._running = threading.Event()
        self._speech_active = threading.Event()
        self._worker: threading.Thread | None = None
        self._transcribe_worker: threading.Thread | None = None
        self._stream: sd.InputStream | None = None
        self._threshold = self.config.energy_threshold
        self._noise_samples: list[float] = []
        self._threshold_lock = threading.Lock()
        self._last_level_at = 0.0
        self._smoothed_energy = 0.0
        self._last_partial_text = ""

    @property
    def active_threshold(self) -> float | None:
        with self._threshold_lock:
            return self._threshold

    def set_energy_threshold(self, value: float | None) -> None:
        with self._threshold_lock:
            self._threshold = value
            self._noise_samples.clear()
            self.config.energy_threshold = value

    def start(self) -> None:
        if self._running.is_set():
            return

        import sounddevice as sd

        self._running.set()
        self._last_partial_text = ""
        blocksize = max(1, int(self.config.samplerate * self.config.block_duration))
        self._transcribe_worker = threading.Thread(
            target=self._transcribe_loop,
            name="asr-transcribe-worker",
            daemon=True,
        )
        self._transcribe_worker.start()
        self._worker = threading.Thread(
            target=self._process_loop,
            name="asr-stream-worker",
            daemon=True,
        )
        self._worker.start()
        self._stream = sd.InputStream(
            samplerate=self.config.samplerate,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            device=self.input_device,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._emit_status("listening")

    def stop(self) -> None:
        if not self._running.is_set():
            return

        self._running.clear()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=2.0)
            self._worker = None

        try:
            self._transcribe_queue.put_nowait(None)
        except queue.Full:
            try:
                self._transcribe_queue.get_nowait()
            except queue.Empty:
                pass
            self._transcribe_queue.put_nowait(None)
        if self._transcribe_worker is not None and self._transcribe_worker.is_alive():
            self._transcribe_worker.join(timeout=3.0)
            self._transcribe_worker = None

        self._drain_audio_queue()
        self._emit_status("stopped")

    def _drain_audio_queue(self) -> None:
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if status:
            _logger.warning("Audio status: %s", status)
        if not self._running.is_set():
            return
        chunk = indata.copy()
        try:
            self._audio_queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._audio_queue.put_nowait(chunk)
            except queue.Full:
                pass

    def _process_loop(self) -> None:
        chunks: list[np.ndarray] = []
        silence_samples = 0
        speech_started = False
        last_partial_at = 0.0

        while self._running.is_set():
            try:
                chunk = self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            flat = np.squeeze(chunk)
            instant = float(np.sqrt(np.mean(flat * flat)))
            alpha = self.config.level_smoothing
            if self._smoothed_energy <= 0:
                self._smoothed_energy = instant
            else:
                self._smoothed_energy = alpha * instant + (1 - alpha) * self._smoothed_energy
            energy = self._smoothed_energy

            with self._threshold_lock:
                threshold = self._threshold
                manual = self.config.energy_threshold is not None

            if threshold is None and not manual:
                self._noise_samples.append(energy)
                if len(self._noise_samples) < self.config.calibration_blocks:
                    continue
                noise_floor = float(np.median(self._noise_samples))
                calibrated = max(
                    noise_floor * self.config.energy_multiplier,
                    self.config.min_energy_threshold,
                )
                with self._threshold_lock:
                    self._threshold = calibrated
                    threshold = calibrated

            if threshold is None:
                continue

            trigger = threshold * (
                self.config.speech_start_multiplier if not speech_started else 1.0
            )
            is_speech = energy >= trigger

            if self.on_level is not None:
                now = time.monotonic()
                if now - self._last_level_at >= 0.05:
                    self._last_level_at = now
                    self.on_level(energy, threshold, is_speech)

            chunks.append(flat)
            self._trim_buffer(chunks)

            if is_speech:
                if not speech_started:
                    speech_started = True
                    self._speech_active.set()
                    self._emit_status("speech")
                silence_samples = 0
                audio = self._concat(chunks)
                min_samples = int(self.config.min_speech_duration * self.config.samplerate)
                if (
                    self.on_partial is not None
                    and len(audio) >= min_samples
                    and (time.monotonic() - last_partial_at) >= self.config.partial_interval
                ):
                    window = self._tail_audio(audio, self.config.partial_window_seconds)
                    if self._submit_transcribe(window, "partial"):
                        last_partial_at = time.monotonic()
                continue

            if not speech_started:
                chunks.clear()
                continue

            silence_samples += len(flat)
            silence_seconds = silence_samples / self.config.samplerate
            if silence_seconds < self.config.silence_duration:
                continue

            audio = self._concat(chunks)
            chunks.clear()
            speech_started = False
            silence_samples = 0
            self._speech_active.clear()
            self._emit_status("listening")

            min_samples = int(self.config.min_speech_duration * self.config.samplerate)
            if len(audio) < min_samples:
                continue

            utterance = self._tail_audio(audio, self.config.max_utterance_seconds)
            self._submit_transcribe(utterance, "final")

    def _submit_transcribe(self, audio: np.ndarray, kind: Literal["partial", "final"]) -> bool:
        job = _TranscribeJob(audio=audio.astype(np.float32, copy=False), kind=kind)
        try:
            self._transcribe_queue.put_nowait(job)
            return True
        except queue.Full:
            if kind == "final":
                try:
                    self._transcribe_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._transcribe_queue.put_nowait(job)
                    return True
                except queue.Full:
                    return False
            return False

    def _transcribe_loop(self) -> None:
        while self._running.is_set() or not self._transcribe_queue.empty():
            try:
                job = self._transcribe_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if job is None:
                break
            text = self._transcribe(job.audio)
            if not text:
                continue
            if job.kind == "partial" and self.on_partial is not None:
                if text != self._last_partial_text:
                    self._last_partial_text = text
                    self.on_partial(text)
            elif job.kind == "final" and self.on_final is not None:
                self._last_partial_text = ""
                self.on_final(text)

    def _trim_buffer(self, chunks: list[np.ndarray]) -> None:
        max_samples = int(self.config.max_buffer_seconds * self.config.samplerate)
        total = sum(len(chunk) for chunk in chunks)
        while total > max_samples and chunks:
            removed = chunks.pop(0)
            total -= len(removed)

    @staticmethod
    def _concat(chunks: list[np.ndarray]) -> np.ndarray:
        if not chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def _tail_audio(self, audio: np.ndarray, seconds: float) -> np.ndarray:
        max_samples = int(seconds * self.config.samplerate)
        if len(audio) <= max_samples:
            return audio
        return audio[-max_samples:].astype(np.float32, copy=False)

    def _transcribe(self, audio: np.ndarray) -> str:
        min_rms = max(
            self.config.min_transcribe_rms,
            (self._threshold or self.config.min_energy_threshold) * 0.45,
        )
        if not audio_loud_enough(audio, min_rms):
            return ""
        try:
            segments, info = self._model.transcribe(
                audio,
                language=self.language,
                task=self.task,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
                condition_on_previous_text=False,
                no_speech_threshold=0.75,
                log_prob_threshold=-0.5,
                compression_ratio_threshold=2.0,
                initial_prompt="以下是简体中文。" if self.language == "zh" else None,
            )
            if getattr(info, "language_probability", 1.0) < 0.5:
                return ""
            parts: list[str] = []
            for segment in segments:
                if getattr(segment, "no_speech_prob", 0.0) > 0.5:
                    continue
                if getattr(segment, "avg_logprob", 0.0) < -0.8:
                    continue
                cleaned = filter_transcript(
                    segment.text.strip(),
                    no_speech_prob=getattr(segment, "no_speech_prob", None),
                )
                if cleaned:
                    parts.append(cleaned)
            return to_simplified_chinese("".join(parts).strip(), self.language)
        except Exception as exc:
            _logger.exception("Transcribe failed: %s", exc)
            return ""

    def _emit_status(self, status: str) -> None:
        if self.on_status is not None:
            self.on_status(status)
