"""桌宠终端日志与 TTS 进度条。"""

from __future__ import annotations

import os
import sys
import threading
import time
import logging

logger = logging.getLogger(__name__)

# 设为 1/true 可打开 TTS 分句/合成步骤等详细日志；默认仅播放与失败
_VERBOSE = os.getenv("PET_VERBOSE", "0").strip().lower() in ("1", "true", "yes", "on")

_BAR_LOCK = threading.Lock()
_ACTIVE_BAR = None


def pet_console_verbose() -> bool:
    return _VERBOSE


def configure_immersive_logging() -> None:
    """默认不向终端刷在场感/日程等内部 INFO（设 PET_VERBOSE=1 可恢复）。"""
    if _VERBOSE:
        return
    for name in (
        "pnn.pet.presence",
        "pnn.pet.reminders",
        "pnn.pet.api_guard",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def log_weather_query(
    city: str,
    line: str,
    *,
    ok: bool = True,
    via: str = "playwright/msn",
    horizon: str = "",
) -> None:
    """终端可见：MSN 天气是否已抓取（Playwright 直抓，不走 MCP）。"""
    name = (city or "").strip() or "?"
    body = (line or "").strip()
    channel = (via or "playwright/msn").strip()
    hz = f" horizon={horizon}" if horizon else ""
    if ok and body:
        print(f"[pet-llm] [weather] {channel}{hz} {name}: {body}", flush=True)
    elif name != "?":
        print(f"[pet-llm] [weather] {channel}{hz} {name}: 查询失败或无数据", flush=True)


def log_chat_user_line(message: str, *, proactive: bool = False) -> None:
    """终端用户行：主动/internal 轮次不打印占位句。"""
    if proactive:
        logger.debug("internal proactive turn")
        return
    from pnn.memory.sanitize import is_system_proactive_turn

    if is_system_proactive_turn(message):
        return
    preview = (message or "").replace("\n", " ")[:120]
    if not preview:
        return
    print(f"[pet-llm] 用户: {preview}", flush=True)


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
    from pnn.pet.reply_text import terminal_text_for_reply

    body = terminal_text_for_reply(text)
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
