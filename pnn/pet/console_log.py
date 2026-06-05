"""桌宠终端日志与 TTS 进度条。"""

from __future__ import annotations

import os
import sys
import threading
import time

# 设为 1/true 可打开 TTS 分句/合成步骤等详细日志；默认仅播放与失败
_VERBOSE = os.getenv("PET_VERBOSE", "0").strip().lower() in ("1", "true", "yes", "on")

_BAR_LOCK = threading.Lock()
_ACTIVE_BAR = None


def pet_console_verbose() -> bool:
    return _VERBOSE


def tts_terminal_bar_enabled() -> bool:
    """默认关闭单行进度条，仅保留 [pet-tts] 文本日志；需条形进度时设 PET_TTS_BAR=1。"""
    if os.getenv("PET_TTS_BAR", "0").strip().lower() in ("1", "true", "yes", "on"):
        return sys.stdout.isatty()
    return False


def suppress_live2d_log() -> None:
    """关闭 live2d-py 原生日志（避免刷屏 Set expression）。"""
    try:
        import live2d.v3 as l2d_v3

        l2d_v3.enableLog(False)
        if hasattr(l2d_v3, "setLogLevel"):
            l2d_v3.setLogLevel(l2d_v3.Live2DLogLevels.LV_ERROR)
    except Exception:
        pass


def log_ai_reply(text: str, *, expression: str | None = None) -> None:
    del expression
    body = (text or "").strip()
    if not body:
        return
    print(f"[pet-ai] {body}", flush=True)


def log_voice_line(emotion_tag: str | None, text: str) -> None:
    """终端输出：情绪标签 + 译后/展示用台词（默认始终显示）。"""
    body = (text or "").strip()
    if not body:
        return
    emo = (emotion_tag or "").strip()
    if emo:
        print(f"[pet-tts] [{emo}] {body}", flush=True)
    else:
        print(f"[pet-tts] {body}", flush=True)


# 默认终端仅输出 TTS 失败；详细步骤设 PET_VERBOSE=1
def log_tts(stage: str, detail: str = "") -> None:
    if stage != "失败" and not _VERBOSE:
        return
    line = f"[pet-tts] {stage}"
    if detail:
        line = f"{line} — {detail}"
    print(line, flush=True)


def _estimate_wav_bytes(text: str) -> int:
    """按字数粗估 WAV 体积，用于进度条在收流前的增长。"""
    n = len((text or "").strip())
    return max(48_000, n * 5_200)


class TtsTerminalBar:
    """终端单行条形进度（\\r 刷新，仅 TTY 下显示）。"""

    WIDTH = 36

    def __init__(self) -> None:
        self._label = "语音合成"
        self._active = False
        self._t0 = 0.0

    def start(self, label: str = "语音合成") -> None:
        global _ACTIVE_BAR
        self._label = (label or "语音合成").strip()
        self._active = True
        self._t0 = time.monotonic()
        with _BAR_LOCK:
            if _ACTIVE_BAR is not None and _ACTIVE_BAR is not self:
                _ACTIVE_BAR.abort()
            _ACTIVE_BAR = self
            self._draw(0.0, "准备…")

    def update(self, percent: float, detail: str = "") -> None:
        if self._active:
            self._draw(percent, detail)

    def _draw(self, percent: float, detail: str = "") -> None:
        pct = max(0.0, min(100.0, float(percent)))
        if not sys.stdout.isatty():
            return
        filled = int(self.WIDTH * pct / 100.0)
        bar = "█" * filled + "░" * (self.WIDTH - filled)
        tail = f" {detail}" if detail else ""
        # 行尾空格避免残留字符
        line = f"\r[pet-tts] {self._label} |{bar}| {pct:5.1f}%{tail}    "
        sys.stdout.write(line)
        sys.stdout.flush()

    def finish(self, detail: str = "完成") -> None:
        global _ACTIVE_BAR
        if not self._active:
            return
        self._draw(100.0, detail)
        if sys.stdout.isatty():
            sys.stdout.write("\n")
            sys.stdout.flush()
        self._active = False
        with _BAR_LOCK:
            if _ACTIVE_BAR is self:
                _ACTIVE_BAR = None

    def abort(self) -> None:
        global _ACTIVE_BAR
        if self._active and sys.stdout.isatty():
            sys.stdout.write("\n")
            sys.stdout.flush()
        self._active = False
        with _BAR_LOCK:
            if _ACTIVE_BAR is self:
                _ACTIVE_BAR = None


def estimate_tts_wav_bytes(text: str) -> int:
    return _estimate_wav_bytes(text)
