"""TTS 音频播放与口型驱动（WavHandler + sounddevice）。"""

from __future__ import annotations

import threading
import wave
from pathlib import Path

import numpy as np

from pnn.core.runtime_files import alloc_runtime_path


class LipSyncPlayer:
    """在后台线程播放 WAV，主线程通过 WavHandler 读取 RMS 驱动口型。"""

    def __init__(self) -> None:
        self._wav = None
        self._playing = False
        self._thread: threading.Thread | None = None
        self._done = threading.Event()
        self._done.set()
        self._lock = threading.Lock()

    def _ensure_wav(self):
        if self._wav is None:
            from live2d.utils.lipsync import WavHandler

            self._wav = WavHandler()
        return self._wav

    @property
    def is_playing(self) -> bool:
        return self._playing

    def playback_active(self) -> bool:
        """音频线程是否仍在运行（比 is_playing 更可靠）。"""
        if self._playing:
            return True
        if self._thread is not None and self._thread.is_alive():
            return True
        return False

    def start(self, wav_bytes: bytes) -> Path:
        with self._lock:
            return self._start_unlocked(wav_bytes)

    def _start_unlocked(self, wav_bytes: bytes) -> Path:
        import sounddevice as sd

        self._stop_unlocked()
        path = alloc_runtime_path(".wav", subdir="playback")
        path.write_bytes(wav_bytes)
        wav = self._ensure_wav()
        wav.Start(str(path))
        self._done.clear()
        self._playing = True

        def _play() -> None:
            try:
                with wave.open(str(path), "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    if not frames:
                        print("[pet-tts] 播放失败：WAV 无音频数据", flush=True)
                        return
                    data = np.frombuffer(frames, dtype=np.int16)
                    channels = wf.getnchannels()
                    if channels > 1:
                        data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)
                    rate = wf.getframerate()
                    if rate <= 0 or len(data) == 0:
                        print("[pet-tts] 播放失败：无效采样率或空缓冲", flush=True)
                        return
                    sd.play(data, rate)
                    sd.wait()
            except Exception as exc:
                print(f"[pet-tts] 播放失败: {exc}", flush=True)
            finally:
                self._playing = False
                wav = self._ensure_wav()
                wav.ReleasePcmData()
                self._done.set()
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

        nbytes = len(wav_bytes)
        self._thread = threading.Thread(target=_play, daemon=True, name="pet-tts-play")
        self._thread.start()
        print(f"[pet-tts] 播放线程已启动（{nbytes} 字节）", flush=True)
        return path

    def wait_done(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def mouth_open_y(self, gain: float = 3.0) -> float:
        if not self._playing:
            return 0.0
        wav = self._ensure_wav()
        wav.Update()
        return min(1.0, wav.GetRms() * gain)

    def stop(self) -> None:
        with self._lock:
            self._stop_unlocked()

    def _stop_unlocked(self) -> None:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        self._playing = False
        self._done.set()
        if self._wav is not None:
            self._wav.ReleasePcmData()
        t = self._thread
        self._thread = None
        if t is not None and t.is_alive():
            t.join(timeout=0.05)


def concat_wav_bytes(parts: list[bytes]) -> bytes:
    """将多段 WAV 按采样参数拼接为一段。"""
    import io

    if not parts:
        return b""
    if len(parts) == 1:
        return parts[0]

    out_buf = io.BytesIO()
    params = None
    frames: list[bytes] = []
    for data in parts:
        if not data or len(data) < 44:
            continue
        with wave.open(io.BytesIO(data), "rb") as src:
            p = src.getparams()
            if params is None:
                params = p
            elif (p.nchannels, p.sampwidth, p.framerate) != (
                params.nchannels,
                params.sampwidth,
                params.framerate,
            ):
                continue
            frames.append(src.readframes(src.getnframes()))
    if params is None or not frames:
        return parts[0]
    with wave.open(out_buf, "wb") as dst:
        dst.setparams(params)
        for chunk in frames:
            dst.writeframes(chunk)
    return out_buf.getvalue()
