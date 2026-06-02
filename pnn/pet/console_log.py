"""桌宠终端日志。"""

from __future__ import annotations

import os
import threading
import time

# 设为 0/false 可关闭 TTS 心跳类日志（阶段 1/4～4/4 始终输出）
_VERBOSE = os.getenv("PET_VERBOSE", "1").strip().lower() not in ("0", "false", "no", "off")


def pet_console_verbose() -> bool:
    return _VERBOSE


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
    body = (text or "").strip()
    if not body:
        return
    print(f"[pet-ai] ========== AI 回复（{len(body)} 字）==========", flush=True)
    print(body, flush=True)
    if expression:
        print(f"[pet-ai] 匹配表情: {expression}", flush=True)
    print("[pet-ai] ========================================", flush=True)


def log_tts(stage: str, detail: str = "") -> None:
    line = f"[pet-tts] {stage}"
    if detail:
        line = f"{line} — {detail}"
    print(line, flush=True)


class TtsProgressReporter:
    """TTS 合成等待期间定时输出进度（终端）。"""

    def __init__(self, interval_sec: float = 3.0) -> None:
        self._interval = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0
        self._phase = ""

    def start(self, phase: str) -> None:
        self._phase = phase
        self._t0 = time.monotonic()
        self._stop.clear()
        log_tts("进度", f"{phase}…")
        if not _VERBOSE:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="pet-tts-progress")
        self._thread.start()

    def _run(self) -> None:
        tick = 0
        while not self._stop.wait(self._interval):
            tick += 1
            elapsed = time.monotonic() - self._t0
            log_tts("进度", f"{self._phase} 已 {elapsed:.0f}s（第 {tick} 次心跳）")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
