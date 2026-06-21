"""TTS 音频播放与口型驱动（sounddevice + 本地 RMS）。"""

from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

import numpy as np

from pnn.core.runtime_files import alloc_runtime_path


class LipSyncPlayer:
    """在后台线程播放 WAV，主线程按播放进度读取 RMS 驱动口型。"""

    def __init__(self) -> None:
        self._playing = False
        self._thread: threading.Thread | None = None
        self._done = threading.Event()
        self._done.set()
        self._lock = threading.Lock()
        self._pcm_mono: np.ndarray | None = None
        self._sample_rate = 0
        self._lip_start = 0.0
        self._lip_offset = 0
        self._lip_rms = 0.0

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

    def _clear_lipsync(self) -> None:
        self._pcm_mono = None
        self._sample_rate = 0
        self._lip_start = 0.0
        self._lip_offset = 0
        self._lip_rms = 0.0

    def _load_pcm(self, wav_bytes: bytes) -> tuple[np.ndarray, np.ndarray, int] | None:
        """返回 (int16 播放, float32 口型, sample_rate)。"""
        import io

        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                frames = wf.readframes(wf.getnframes())
                rate = wf.getframerate()
                channels = wf.getnchannels()
        except Exception:
            return None
        if not frames or rate <= 0:
            return None
        data = np.frombuffer(frames, dtype=np.int16)
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)
        if len(data) < 64:
            return None
        mono_f = data.astype(np.float32)
        peak = float(np.max(np.abs(mono_f)))
        if peak > 0:
            mono_f /= peak
        return data, mono_f, int(rate)

    def start(self, wav_bytes: bytes) -> Path:
        with self._lock:
            return self._start_unlocked(wav_bytes)

    def _start_unlocked(self, wav_bytes: bytes) -> Path:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise ImportError(
                "未安装 sounddevice，桌宠无法播放语音。请在项目目录执行："
                " pip install sounddevice"
            ) from exc

        self._stop_unlocked()
        path = alloc_runtime_path(".wav", subdir="playback")
        ok, reason, dur = wav_playback_info(wav_bytes)
        if not ok:
            print(f"[pet-tts] 播放跳过：{reason}", flush=True)
            self._playing = False
            self._done.set()
            raise ValueError(reason)

        loaded = self._load_pcm(wav_bytes)
        if loaded is None:
            self._playing = False
            self._done.set()
            raise ValueError("WAV 口型数据加载失败")

        play_data, pcm_mono, rate = loaded
        self._clear_lipsync()
        self._pcm_mono = pcm_mono
        self._sample_rate = rate
        self._done.clear()

        def _play() -> None:
            try:
                path.write_bytes(wav_bytes)
                sd.play(play_data, rate)
                sd.wait()
            except Exception as exc:
                print(f"[pet-tts] 播放失败: {exc}", flush=True)
            finally:
                self._playing = False
                self._clear_lipsync()
                self._done.set()
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

        self._lip_start = time.time()
        self._lip_offset = 0
        self._lip_rms = 0.0
        self._playing = True
        self._thread = threading.Thread(target=_play, daemon=True, name="pet-tts-play")
        self._thread.start()
        print(
            f"[pet-tts] 播放线程已启动（{len(wav_bytes)} 字节，约 {dur:.1f}s）",
            flush=True,
        )
        return path

    def wait_done(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def mouth_open_y(self, gain: float = 3.0) -> float:
        if not self._playing or self._pcm_mono is None or self._sample_rate <= 0:
            return 0.0
        current = int((time.time() - self._lip_start) * self._sample_rate)
        n = len(self._pcm_mono)
        current = min(max(current, 0), n)
        if current <= self._lip_offset:
            return min(1.0, self._lip_rms * gain)
        frag = self._pcm_mono[self._lip_offset:current]
        self._lip_offset = current
        if len(frag) > 0:
            self._lip_rms = float(np.sqrt(np.mean(np.square(frag))))
        return min(1.0, self._lip_rms * gain)

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
        self._clear_lipsync()
        t = self._thread
        self._thread = None
        if t is not None and t.is_alive():
            t.join(timeout=0.05)


def wav_playback_info(wav_bytes: bytes) -> tuple[bool, str, float]:
    """检查 WAV 是否可播放且有可听内容。返回 (ok, reason, duration_sec)。"""
    import io

    if not wav_bytes or len(wav_bytes) < 44:
        return False, "音频过短", 0.0
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            rate = wf.getframerate()
            channels = wf.getnchannels()
    except Exception as exc:
        return False, f"WAV 解析失败: {exc}", 0.0
    if not frames or rate <= 0:
        return False, "无 PCM 数据", 0.0
    data = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if len(data) < 64:
        return False, "采样过短", 0.0
    duration = len(data) / float(rate)
    rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
    if rms < 25.0:
        return False, f"近乎静音 (RMS={rms:.0f})", duration
    return True, "ok", duration


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
