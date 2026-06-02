"""TTS 音频播放与口型驱动（WavHandler + sounddevice）。"""

from __future__ import annotations

import os
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np
from live2d.utils.lipsync import WavHandler


class LipSyncPlayer:
    """在后台线程播放 WAV，主线程通过 WavHandler 读取 RMS 驱动口型。"""

    def __init__(self) -> None:
        self.wav = WavHandler()
        self._playing = False
        self._thread: threading.Thread | None = None
        self._done = threading.Event()
        self._done.set()
        self._lock = threading.Lock()

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
        fd, name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        path = Path(name)
        path.write_bytes(wav_bytes)
        self.wav.Start(str(path))
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
                self.wav.ReleasePcmData()
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
        self.wav.Update()
        return min(1.0, self.wav.GetRms() * gain)

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
        self.wav.ReleasePcmData()
        t = self._thread
        self._thread = None
        if t is not None and t.is_alive():
            t.join(timeout=0.8)
