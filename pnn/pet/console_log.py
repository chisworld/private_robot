"""桌宠终端日志与 TTS 进度条。"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
import logging
import shutil

logger = logging.getLogger(__name__)

_SENTENCE_END = re.compile(r"[。！？!?、\n]")

# 设为 1/true 可打开 TTS 分句/合成步骤等详细日志；默认仅播放与失败
_VERBOSE = os.getenv("PET_VERBOSE", "0").strip().lower() in ("1", "true", "yes", "on")

_BAR_LOCK = threading.Lock()
_ACTIVE_BAR = None
_LLM_STREAM_LOCK = threading.Lock()
_LLM_STREAM_WRITER: "LlmStreamTerminalWriter | None" = None
_PREFILL_LOCK = threading.Lock()
_PREFILL_STOP: threading.Event | None = None
_PREFILL_THREAD: threading.Thread | None = None


def _stream_chunk_chars() -> int:
    raw = os.getenv("PET_LLM_STREAM_CHUNK", "8").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 8


def _stream_chunk_interval() -> float:
    raw = os.getenv("PET_LLM_STREAM_INTERVAL", "0.35").strip()
    try:
        return max(0.05, float(raw))
    except ValueError:
        return 0.35


def _pet_llm_stream_mode() -> str:
    """summary=仅结束时打印回复行；line/1=增量小块；0=完全静默。"""
    return os.getenv("PET_LLM_STREAM", "summary").strip().lower()


def llm_stream_terminal_enabled() -> bool:
    """终端增量显示 LLM 流式正文（[pet-llm] +）；默认关闭，设 PET_LLM_STREAM=line 可打开。"""
    return _pet_llm_stream_mode() in (
        "1",
        "true",
        "yes",
        "on",
        "line",
        "lines",
        "bar",
        "cr",
        "inline",
        "stream",
    )


def llm_stream_reply_line_enabled() -> bool:
    """结束时打印 [pet-llm] 回复: 一行；PET_LLM_STREAM=0/silent 时关闭。"""
    return _pet_llm_stream_mode() not in ("0", "false", "no", "off", "silent")


def llm_stream_use_carriage_return() -> bool:
    """单行 \\r 刷新：Linux/macOS TTY 可用；Windows 默认按句换行避免乱码。"""
    mode = _pet_llm_stream_mode()
    if mode in ("bar", "cr", "inline"):
        return sys.stdout.isatty()
    if mode in ("line", "lines", "stream", "1", "true", "yes", "on"):
        return False
    if sys.platform == "win32":
        return False
    return sys.stdout.isatty()


def configure_pet_stdio_utf8() -> None:
    """Windows 终端默认 UTF-8（配合 启动桌宠.bat 的 chcp 65001）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


class LlmStreamTerminalWriter:
    """终端 LLM 流式输出：Windows 按小块换行；Linux/macOS TTY 可单行 \\r 刷新。"""

    def __init__(self) -> None:
        self._active = False
        self._printed_final = False
        self._last_emitted_index = 0
        self._last_line_len = 0
        self._last_partial_at = 0.0

    def _width(self) -> int:
        try:
            return max(40, shutil.get_terminal_size((100, 24)).columns - 20)
        except Exception:
            return 80

    def _preview(self, full: str) -> str:
        body = (full or "").replace("\r", " ").replace("\n", " ")
        w = self._width()
        if len(body) <= w:
            return body
        return "…" + body[-(w - 1) :]

    def _write_inline(self, preview: str) -> None:
        line = f"[pet-llm] 生成: {preview}"
        pad = max(0, self._last_line_len - len(line))
        sys.stdout.write(f"\r{line}{' ' * pad}")
        if sys.platform == "win32":
            sys.stdout.write("\033[K")
        self._last_line_len = len(line)
        sys.stdout.flush()

    def _emit_chunk(self, piece: str) -> None:
        text = (piece or "").replace("\r", " ").replace("\n", " ")
        if not text.strip():
            return
        print(f"[pet-llm] + {text}", flush=True)
        self._active = True

    def _flush_line_mode(self, full: str, *, force_tail: bool = False) -> None:
        chunk_min = _stream_chunk_chars()
        interval = _stream_chunk_interval()
        while self._last_emitted_index < len(full):
            rest = full[self._last_emitted_index :]
            m = _SENTENCE_END.search(rest)
            if m:
                piece = rest[: m.end()]
                self._emit_chunk(piece)
                self._last_emitted_index += len(piece)
                self._last_partial_at = time.monotonic()
                continue
            if force_tail:
                if rest.strip():
                    self._emit_chunk(rest)
                self._last_emitted_index = len(full)
                break
            now = time.monotonic()
            if len(rest) >= chunk_min and now - self._last_partial_at >= interval:
                piece = rest[:chunk_min]
                self._emit_chunk(piece)
                self._last_emitted_index += len(piece)
                self._last_partial_at = now
            break

    def update(self, full: str) -> None:
        if not llm_stream_terminal_enabled():
            return
        body = full or ""
        if not body.strip():
            return
        if llm_stream_use_carriage_return():
            preview = self._preview(body)
            if not self._active:
                sys.stdout.write(f"[pet-llm] 生成: {preview}")
                self._active = True
            else:
                self._write_inline(preview)
            return
        if not sys.stdout.isatty():
            self._flush_line_mode(body, force_tail=False)
            return
        self._flush_line_mode(body, force_tail=False)

    def finish(self, full: str) -> bool:
        """结束流式行；若已输出则返回 True（避免重复 log_ai_reply）。"""
        body = (full or "").strip()
        if llm_stream_terminal_enabled():
            if llm_stream_use_carriage_return() and self._active and sys.stdout.isatty():
                sys.stdout.write("\n")
                sys.stdout.flush()
            elif body:
                self._flush_line_mode(full or "", force_tail=True)
        if body:
            from pnn.pet.reply_text import terminal_text_for_reply

            text = terminal_text_for_reply(full) or body
            preview = text.replace("\n", " ")
            if len(preview) > 500:
                preview = preview[:500] + "…"
            if llm_stream_reply_line_enabled():
                print(f"[pet-llm] 回复: {preview}", flush=True)
            self._printed_final = True
        self._active = False
        self._last_emitted_index = 0
        self._last_line_len = 0
        return self._printed_final

    def abort(self) -> None:
        if self._active and llm_stream_use_carriage_return() and sys.stdout.isatty():
            sys.stdout.write("\n")
            sys.stdout.flush()
        self._active = False
        self._printed_final = False
        self._last_emitted_index = 0
        self._last_line_len = 0


def _llm_stream_writer() -> LlmStreamTerminalWriter:
    global _LLM_STREAM_WRITER
    with _LLM_STREAM_LOCK:
        if _LLM_STREAM_WRITER is None:
            _LLM_STREAM_WRITER = LlmStreamTerminalWriter()
        return _LLM_STREAM_WRITER


def log_llm_prefill_stop(*, got_token: bool = False) -> None:
    global _PREFILL_STOP, _PREFILL_THREAD
    with _PREFILL_LOCK:
        stop = _PREFILL_STOP
        _PREFILL_STOP = None
        thread = _PREFILL_THREAD
        _PREFILL_THREAD = None
    if stop is not None:
        stop.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=0.05)
    if got_token and stop is not None:
        print("[pet-llm] 首 token 已到 ↓", flush=True)


def log_llm_prefill_start(route: str = "") -> None:
    if str(route or "").strip() != "local_qwen":
        return

    def _heartbeat(stop: threading.Event) -> None:
        start = time.monotonic()
        try:
            interval = max(5.0, float(os.getenv("PET_LLM_PREFILL_INTERVAL", "15")))
        except ValueError:
            interval = 15.0
        while not stop.wait(interval):
            elapsed = int(time.monotonic() - start)
            print(f"[pet-llm] prefill 中… 已等待 {elapsed}s", flush=True)

    global _PREFILL_STOP, _PREFILL_THREAD
    log_llm_prefill_stop()
    stop = threading.Event()
    with _PREFILL_LOCK:
        _PREFILL_STOP = stop
        _PREFILL_THREAD = threading.Thread(
            target=_heartbeat,
            args=(stop,),
            daemon=True,
            name="pet-llm-prefill",
        )
        _PREFILL_THREAD.start()


def log_llm_stream_reset() -> None:
    log_llm_prefill_stop()
    with _LLM_STREAM_LOCK:
        global _LLM_STREAM_WRITER
        if _LLM_STREAM_WRITER is not None:
            _LLM_STREAM_WRITER.abort()
            _LLM_STREAM_WRITER = LlmStreamTerminalWriter()


def log_llm_stream_update(full: str) -> None:
    if (full or "").strip():
        log_llm_prefill_stop(got_token=True)
    _llm_stream_writer().update(full)


def log_llm_stream_finish(full: str) -> bool:
    log_llm_prefill_stop()
    return _llm_stream_writer().finish(full)


def log_llm_stream_abort() -> None:
    log_llm_prefill_stop()
    _llm_stream_writer().abort()


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


def log_llm_route(info: dict) -> None:
    """终端可见：本条对话实际使用的 LLM 路由。"""
    from pnn.llm.routing import format_route_terminal

    route = str(info.get("route") or "")
    if route == "code_direct":
        print("[pet-llm] 路由: 本地代码文件读取", flush=True)
        return
    if route == "mcp_blocked":
        print(f"[pet-llm] 路由: {info.get('label') or '需要 MCP'}", flush=True)
        return
    extra = "（含 MSN 天气）" if info.get("weather") else ""
    print(f"[pet-llm] 路由: {format_route_terminal(info)}{extra}", flush=True)
    if route == "local_qwen":
        lite = info.get("local_chat_lite")
        hist = info.get("local_history_cap")
        tok = info.get("local_max_tokens")
        caps = ""
        if hist is not None and tok is not None:
            caps = f" history≤{hist} max_tokens={tok}"
        if lite:
            print(
                f"[pet-llm] 精简上下文（更快）：无记忆 / 短标签说明{caps}",
                flush=True,
            )
        else:
            print(
                f"[pet-llm] 标准本地上下文（含记忆与完整表情说明{caps}）",
                flush=True,
            )
        print(
            "[pet-llm] 等待首 token（prefill，本地 35B 常见 30s～2min；"
            "开语音时气泡会保持「…」直到首句合成）…",
            flush=True,
        )
        log_llm_prefill_start(route="local_qwen")


def log_nsfw_toggle(
    enabled: bool,
    *,
    local_model: str,
    local_base: str,
    cloud_model: str,
) -> None:
    """勾选 NSFW 时在终端提示（保存后生效）。"""
    if enabled:
        print(
            f"[pet-llm] NSFW 已勾选 → 点击「保存设置」后，日常闲聊将走本地 "
            f"{local_model} @ {local_base.rstrip('/')}",
            flush=True,
        )
    else:
        print(
            f"[pet-llm] NSFW 已关闭 → 点击「保存设置」后，日常闲聊将走 DeepSeek {cloud_model}",
            flush=True,
        )


def log_nsfw_saved(
    enabled: bool,
    *,
    local_model: str,
    local_base: str,
    cloud_model: str,
) -> None:
    """保存设置后确认 NSFW 与日常闲聊模型。"""
    if enabled:
        print(
            f"[pet-llm] ✓ 已保存：NSFW 开启，日常闲聊 → 本地 "
            f"{local_model} @ {local_base.rstrip('/')}",
            flush=True,
        )
    else:
        print(
            f"[pet-llm] ✓ 已保存：NSFW 关闭，日常闲聊 → DeepSeek {cloud_model}",
            flush=True,
        )


def log_llm_startup_banner() -> None:
    """桌宠启动时在终端显示当前 NSFW 与日常闲聊路由。"""
    try:
        from pnn.llm.config_store import load_llm_config
        from pnn.llm.local_qwen import local_llm_health
        from pnn.llm.routing import describe_chat_route, format_route_terminal

        cfg = load_llm_config()
        info = describe_chat_route(cfg, "你好")
        nsfw = "开启" if cfg.nsfw_enabled else "关闭"
        print(
            f"[pet-llm] NSFW {nsfw} | 日常闲聊: {format_route_terminal(info)}",
            flush=True,
        )
        if cfg.nsfw_enabled:
            ok, detail = local_llm_health(cfg.local_model_base_url)
            state = "就绪" if ok else "未就绪"
            print(f"[pet-llm] 本地 Qwen: {state} — {detail}", flush=True)
    except Exception as exc:
        print(f"[pet-llm] 读取 LLM 配置失败: {exc}", flush=True)


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


def log_voice_line(
    emotion_tag: str | None,
    text: str,
    *,
    tts_source: str = "",
) -> None:
    """终端输出：情绪标签 + 气泡译后台词；若与 TTS 原文不同则附带朗读稿。"""
    body = (text or "").strip()
    if not body:
        return
    emo = (emotion_tag or "").strip()
    synth = (tts_source or "").strip()
    suffix = ""
    if synth and synth != body:
        suffix = f"  →朗读:{synth.replace(chr(10), ' ')[:80]}"
    if emo:
        print(f"[pet-tts] [{emo}] {body}{suffix}", flush=True)
    else:
        print(f"[pet-tts] {body}{suffix}", flush=True)


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
