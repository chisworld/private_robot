"""桌宠对话编排：LLM 流式 → 表情 → TTS 口型。"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QElapsedTimer, Qt, QThread, QTimer, Signal

from pnn.pet.api_client import ChatMessage, PetApiClient
from pnn.pet.audio import LipSyncPlayer
from pnn.pet.console_log import log_ai_reply, log_chat_user_line, log_llm_stream_abort, log_llm_stream_finish, log_llm_stream_reset, log_llm_stream_update, log_tts, log_voice_line, pet_console_verbose
from pnn.pet.action_catalog import build_llm_action_instruction
from pnn.pet.expression_catalog import build_llm_expression_instruction, discover_expression_names
from pnn.pet.speech_sync import (
    build_coherence_prompt_addon,
    pick_action_for_segment,
    pick_expression_for_segment,
    resolve_segment_emotion_tag,
)
from pnn.pet.expression_tags import (
    parse_tagged_piece,
    pull_final_tagged_chunk,
    pull_tagged_tts_chunks,
    strip_expression_tags,
)

if TYPE_CHECKING:
    from pnn.pet.live2d_widget import Live2DWidget

logger = logging.getLogger(__name__)

PROACTIVE_TRIGGER_LABELS = {
    "idle": "空闲搭话",
    "afk": "挂机轻语",
    "time_greeting": "时段问候",
    "holiday_greeting": "节日问候",
    "absence_return": "久别重逢",
    "window_greet": "开窗问候",
    "session_resume": "接续对话",
    "writing_nudge": "写作捧哏",
}

_BUBBLE_HAS_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")


def _default_expression() -> str:
    from pnn.pet.paths import DEFAULT_EXPRESSION

    return DEFAULT_EXPRESSION

# 分句合成并发：GPT-SoVITS 单进程推理，桌宠侧串行避免双请求卡死
MAX_TTS_SYNTH_PARALLEL = 1
# 同情绪标签的连续句合并为一次 TTS（减少多次冷启动）；首句仍立即送出以尽快开读
TTS_COALESCE_MAX_CHARS = 200
# 单轮对话最多排队分句数，防止流式重复切分撑爆线程与内存
MAX_TTS_SEGMENTS = 32
# 对话历史上限（条），避免请求体与内存无限增长
MAX_HISTORY_MESSAGES = 40


def _start_thread(worker: QThread) -> None:
    """子线程结束后自动 deleteLater，避免 QThread 对象堆积导致卡顿。"""
    worker.finished.connect(worker.deleteLater)
    worker.start()


def _qthread_running(worker: QThread | None) -> bool:
    if worker is None:
        return False
    try:
        return worker.isRunning()
    except RuntimeError:
        return False


class _ChatWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)
    delta_changed = Signal(str)
    agent_status = Signal(str)

    def __init__(
        self,
        api: PetApiClient,
        message: str,
        history: list[ChatMessage],
        *,
        stream_deltas: bool,
        pet_expression_prompt: str | None = None,
        image_base64: str = "",
        image_mime: str = "image/png",
        image_analysis: str = "",
        cancel: threading.Event | None = None,
        defer_memory: bool = False,
        internal_turn: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._message = message
        self._history = history
        self._stream_deltas = stream_deltas
        self._pet_expression_prompt = pet_expression_prompt
        self._image_base64 = image_base64
        self._image_mime = image_mime
        self._image_analysis = image_analysis
        self._cancel = cancel
        self._defer_memory = defer_memory
        self._internal_turn = internal_turn

    def run(self) -> None:
        preview = self._message.replace("\n", " ")[:120]
        if self._image_base64:
            preview = f"[附图] {preview}".strip()
        log_chat_user_line(preview, proactive=self._internal_turn)

        def on_delta(full: str) -> None:
            if self._cancel is not None and self._cancel.is_set():
                return
            log_llm_stream_update(full)
            self.delta_changed.emit(full)

        if not self._image_base64:
            try:
                from pnn.agent.code_direct import try_direct_workspace_read_reply

                direct = try_direct_workspace_read_reply(self._message)
            except Exception as exc:
                logger.debug("代码直达读取跳过: %s", exc)
                direct = None
            if direct:
                print("[pet-llm] 代码文件直达读取（本地）", flush=True)
                if self._stream_deltas:
                    step = 24
                    acc = ""
                    for i in range(0, len(direct), step):
                        if self._cancel is not None and self._cancel.is_set():
                            return
                        acc = direct[: i + step]
                        on_delta(acc)
                if self._cancel is not None and self._cancel.is_set():
                    return
                self.finished_ok.emit(direct)
                return

        def _on_weather_status(raw: str) -> None:
            try:
                import json

                data = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                return
            if not isinstance(data, dict):
                return
            from pnn.pet.console_log import log_weather_query

            log_weather_query(
                str(data.get("city") or ""),
                str(data.get("line") or ""),
                ok=bool(data.get("ok")),
                via=str(data.get("via") or "playwright/msn"),
                horizon=str(data.get("horizon") or ""),
            )

        def _on_llm_route(info: dict) -> None:
            from pnn.pet.console_log import log_llm_route

            log_llm_route(info)
            route = str(info.get("route") or "")
            if route == "local_qwen":
                self.agent_status.emit(
                    "本地 Qwen 推理中（首 token 可能 1～2 分钟，请稍候）…"
                )
            elif route in ("deepseek", "agent"):
                model = str(info.get("model") or "")
                if route == "agent":
                    self.agent_status.emit("DeepSeek Agent 处理中…")
                else:
                    self.agent_status.emit(
                        f"DeepSeek 云端推理中（{model or 'deepseek'}）…"
                    )
                if info.get("nsfw_enabled") and route == "deepseek":
                    self.agent_status.emit(
                        "提示：NSFW 已开启但未走本地 Qwen，请检查 llama-server 是否就绪"
                    )

        try:
            result = self._api.stream_chat(
                self._message,
                self._history,
                on_delta=on_delta if self._stream_deltas else None,
                on_agent_status=lambda s: self.agent_status.emit(s),
                on_weather_status=_on_weather_status,
                on_llm_route=_on_llm_route,
                pet_expression_prompt=self._pet_expression_prompt,
                image_base64=self._image_base64,
                image_mime=self._image_mime,
                image_analysis=self._image_analysis,
                cancel=self._cancel,
                defer_memory=self._defer_memory,
            )
        except Exception as exc:
            logger.exception("stream_chat failed")
            self.failed.emit(str(exc) or "对话失败")
            return
        if self._cancel is not None and self._cancel.is_set():
            return
        if result.error:
            self.failed.emit(result.error)
        elif (result.text or "").strip():
            self.finished_ok.emit(result.text)
        else:
            self.failed.emit("模型未返回内容")


class _TranslateWorker(QThread):
    """后台翻译，避免百度 API 阻塞 UI 线程。"""

    finished_ok = Signal(str)
    failed = Signal()

    def __init__(self, text: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._text = text

    def run(self) -> None:
        try:
            from pnn.translate.service import translate_service

            if not translate_service.display_translation_for_bubble():
                self.finished_ok.emit(self._text)
                return
            out = translate_service.to_display_chinese(self._text)
            if not (out or "").strip():
                self.failed.emit()
                return
            # 翻译 API 退回日文/原文时：气泡禁止展示，保持「…」
            if (
                out.strip() == self._text.strip()
                and _BUBBLE_HAS_KANA.search(self._text)
            ):
                self.failed.emit()
                return
            self.finished_ok.emit(out)
        except Exception as exc:
            logger.debug("气泡翻译失败: %s", exc)
            self.failed.emit()


@dataclass
class _PlayItem:
    bubble_text: str
    wav: bytes
    on_end: Callable[[], None] | None = None
    bubble_turn: int = 0
    play_id: int = 0
    # 固定问候/提示语：气泡已是最终中文，不再走「…」与百度译中
    bubble_literal: bool = False


class _TtsWorker(QThread):
    """合成完成 payload: list[tuple[朗读子句, wav]]（长句会按标点拆多段）。"""

    finished_ok = Signal(object)
    failed = Signal(str)
    progress_changed = Signal(str, int)

    def __init__(
        self,
        api: PetApiClient,
        text: str,
        *,
        emotion_tag: str | None = None,
        progress_label: str = "",
        cancel: threading.Event | None = None,
        retries: int = 0,
        display_text: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._text = text
        self._emotion_tag = emotion_tag
        self._progress_label = (progress_label or "").strip()
        self._cancel = cancel
        self._retries = max(0, retries)
        self._display_text = (display_text or "").strip()

    def run(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            return
        preview = self._text.replace("\n", " ")[:40]
        try:
            from pnn.characters.reply_lang import active_reply_language
            from pnn.pet.reply_text import terminal_text_for_reply, tts_text_for_reply
            from pnn.tts.text_sanitize import split_for_tts

            lang = active_reply_language()
            display = self._display_text or terminal_text_for_reply(self._text) or self._text.strip()
            tts_source = tts_text_for_reply(self._text, lang)
            log_voice_line(self._emotion_tag, display, tts_source=tts_source)
            segments = split_for_tts(tts_source)
            if not segments:
                self.failed.emit("TTS 文本为空")
                return
            chunks: list[tuple[str, bytes]] = []
            n_seg = len(segments)
            for i, seg in enumerate(segments):
                if self._cancel is not None and self._cancel.is_set():
                    return
                plabel = self._progress_label or preview
                label = plabel if n_seg == 1 else f"语音 {i + 1}/{n_seg}"
                log_tts("合成", f"{label} 开始（{len(seg)} 字）")
                data = self._synthesize_with_retry(seg, lang, progress_label=label)
                if self._cancel is not None and self._cancel.is_set():
                    return
                if not data or len(data) < 44:
                    self.failed.emit("TTS 返回空音频")
                    return
                log_tts("合成", f"{label} 完成（{len(data)} 字节）")
                chunks.append((seg, data))
            if not chunks:
                self.failed.emit("TTS 返回空音频")
                return
            self.finished_ok.emit(chunks)
        except InterruptedError:
            return
        except Exception as exc:
            if self._cancel is not None and self._cancel.is_set():
                return
            log_tts("失败", str(exc))
            self.failed.emit(str(exc))

    def _synthesize_with_retry(self, text: str, lang: str, *, progress_label: str = "") -> bytes:
        import time

        last_err = "TTS 返回空音频"
        for attempt in range(self._retries + 1):
            if self._cancel is not None and self._cancel.is_set():
                raise InterruptedError("TTS 已取消")
            try:
                data = self._api.synthesize_tts(
                    text,
                    text_lang=lang,
                    emotion_id=self._emotion_tag,
                    progress_label=progress_label,
                    log_progress=True,
                    terminal_bar=False,
                    cancel=self._cancel,
                    on_progress=lambda msg, pct: self.progress_changed.emit(msg, pct),
                )
                if data and len(data) >= 44:
                    return data
            except InterruptedError:
                raise
            except Exception as exc:
                last_err = str(exc)
                if attempt < self._retries:
                    log_tts("重试", f"第 {attempt + 2} 次（{last_err[:80]}）")
                    time.sleep(2.0)
                    continue
                raise RuntimeError(last_err) from exc
            if attempt < self._retries:
                log_tts("重试", f"第 {attempt + 2} 次（空音频）")
                time.sleep(2.0)
        raise RuntimeError(last_err)


class _ScreenshotVisionWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        api: PetApiClient,
        image_base64: str,
        image_mime: str,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._image_base64 = image_base64
        self._image_mime = image_mime or "image/png"

    def run(self) -> None:
        try:
            from pnn.llm.vision_client import describe_image_preview

            analysis = describe_image_preview(self._image_base64, self._image_mime)
            self.finished_ok.emit(analysis)
        except Exception as exc:
            self.failed.emit(str(exc))


class _ScreenshotAnalysisTtsWorker(QThread):
    """识图摘要：逐句合成，便于播放时同步显示对应文本。"""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        api: PetApiClient,
        analysis: str,
        lang: str,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._analysis = analysis
        self._lang = lang

    def run(self) -> None:
        import time

        from pnn.characters.reply_lang import normalize_reply_language
        from pnn.pet.screenshot_hint import format_analysis_segments

        code = normalize_reply_language(self._lang)
        segments = format_analysis_segments(self._analysis, code)
        if not segments:
            self.failed.emit("识图摘要为空")
            return
        out: list[tuple[str, bytes]] = []
        for display, tts in segments:
            preview = tts.replace("\n", " ")[:40]
            log_tts("合成", f"摘要句 {preview}")
            last_err = "TTS 返回空音频"
            wav: bytes | None = None
            for attempt in range(3):
                try:
                    wav = self._api.synthesize_tts(tts, text_lang=code)
                    if wav and len(wav) >= 44:
                        break
                except Exception as exc:
                    last_err = str(exc)
                if attempt < 2:
                    log_tts("重试", f"摘要句第 {attempt + 2} 次")
                    time.sleep(2.0)
            if not wav or len(wav) < 44:
                self.failed.emit(last_err)
                return
            # 气泡始终用中文展示句；TTS 为 display(中) 或 ja 朗读稿
            out.append((display, wav))
        log_tts("合成", f"摘要共 {len(out)} 句")
        self.finished_ok.emit(out)


class _TimeGreetingWorker(QThread):
    finished_ok = Signal(bytes, str)
    failed = Signal(str)

    def __init__(
        self,
        api: PetApiClient,
        slot: str,
        lang: str,
        display: str,
        *,
        char_id: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._slot = slot
        self._lang = lang
        self._display = display
        self._char_id = char_id

    def run(self) -> None:
        try:
            from pnn.pet.time_greeting import ensure_time_greeting_wav

            data = ensure_time_greeting_wav(
                self._api,
                self._slot,
                self._lang,
                char_id=self._char_id or None,
            )
            self.finished_ok.emit(data, self._display)
        except Exception as exc:
            self.failed.emit(str(exc))


class _ScreenshotHintWorker(QThread):
    finished_ok = Signal(bytes)
    failed = Signal(str)

    def __init__(
        self,
        api: PetApiClient,
        lang: str,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._lang = lang

    def run(self) -> None:
        try:
            from pnn.pet.screenshot_hint import ensure_screenshot_hint_wav

            data = ensure_screenshot_hint_wav(self._api, self._lang)
            self.finished_ok.emit(data)
        except Exception as exc:
            self.failed.emit(str(exc))


class PetController(QObject):
    """连接 API、Live2D 与双窗口 UI。"""

    status_changed = Signal(str, bool)
    bubble_changed = Signal(str, bool)
    tts_synth_progress = Signal(str, int)
    playback_started = Signal()
    playback_finished = Signal()
    loading_changed = Signal(bool)
    screenshot_analysis_ready = Signal(str)
    turn_completed = Signal(str, str)

    def __init__(
        self,
        api: PetApiClient,
        live2d: Live2DWidget,
        lip: LipSyncPlayer,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._live2d = live2d
        self._lip = lip
        self._history: list[ChatMessage] = []
        self._loading = False
        self._chat_worker: _ChatWorker | None = None
        self._screenshot_hint_worker: _ScreenshotHintWorker | None = None
        self._screenshot_vision_worker: _ScreenshotVisionWorker | None = None
        self._screenshot_analysis_tts_worker: _ScreenshotAnalysisTtsWorker | None = None
        self._time_greeting_worker: _TimeGreetingWorker | None = None
        self._startup_greeting_played = False
        self._pending_screenshot_analysis = ""
        self._screenshot_flow_active = False
        self._screenshot_hint_played = False
        self._screenshot_analysis_played = False
        self._screenshot_analysis_tts_text = ""
        self._screenshot_vision_pending = False
        self._screenshot_hint_display = ""
        self._screenshot_vision_error = ""
        self._answer_text = ""
        self._playback_seq = 0
        self._voice_output_enabled = True
        self._text_only_mode = False
        self._stream_bubble_output = False
        self._tts_spoken_offset = 0
        self._playback_active = False
        self._turn_id = 0
        self._proactive_turn = False
        self._proactive_context = ""
        self._proactive_is_schedule = False
        self._proactive_trigger_kind = ""
        self._chat_tts_finalized_turn = 0

        # 分句朗读：并行合成 + 按序播放
        self._seg_texts: list[str] = []
        self._seg_display_zh: list[str] = []
        self._seg_exprs: list[str] = []
        self._seg_tts_tags: list[str] = []
        self._seg_audio: dict[int, bytes] = {}
        self._seg_actions: dict[int, str] = {}
        self._seg_synth: set[int] = set()
        self._seg_failed: set[int] = set()
        self._seg_seen: set[str] = set()

        self._seg_play_idx = 0
        self._seg_chunk_remain: dict[int, list[tuple[str, bytes]]] = {}
        self._playback_play_id = 0
        self._tts_pending_text = ""
        self._tts_pending_expr = ""
        self._tts_pending_action: str | None = None
        self._tts_pending_emotion = ""
        self._tts_batches_flushed = 0
        self._expr_names: list[str] | None = None
        self._expr_available: set[str] = set()
        self._expr_prompt_char_id: str = ""
        self._pet_expr_prompt: str | None = None
        self._stream_last_expr: str | None = None
        self._stream_last_emotion_tag: str | None = None
        self._raw_answer_text = ""
        self._stream_cancel = threading.Event()
        self._last_status = ""
        self._last_status_err = False
        self._last_mouth = -1.0
        self._delta_throttle = QElapsedTimer()
        self._delta_throttle.start()
        self._last_delta_len = 0
        self._last_bubble_emit_snapshot = ""
        self._display_answer_text = ""
        self._play_queue: list[_PlayItem] = []
        self._translate_worker: _TranslateWorker | None = None
        self._stream_translate_worker: _TranslateWorker | None = None
        self._stream_translate_seq = 0
        self._pending_stream_translate = ""
        self._bubble_translate_seq = 0
        self._last_user_msg = ""
        self._last_char_id = ""
        self._memory_turn_lock = threading.Lock()
        self._memory_extract_lock = threading.Lock()
        self._pending_memory_user = ""
        self._pending_memory_reply = ""
        self._pending_memory_turn_id = 0
        self._pending_memory_extracted: dict | None = None
        self._pending_memory_extract_done = False
        self._pending_memory_extract_turn_id = 0

        self._mouth_timer = QTimer(self)
        self._mouth_timer.setInterval(16)
        self._mouth_timer.timeout.connect(self._poll_mouth)

        self._playback_poll = QTimer(self)
        self._playback_poll.setInterval(80)
        self._playback_poll.timeout.connect(self._tick_playback_poll)
        self._playback_poll_on_end = None
        self._playback_bubble_pending: tuple[str, int, int, bool] | None = None
        self._playback_bubble_wait_ticks = 0
        self._bubble_thinking = False
        self._stall_guard = QTimer(self)
        self._stall_guard.setSingleShot(True)
        self._stall_guard.setInterval(90_000)
        self._stall_guard.timeout.connect(self._recover_stalled_ui)

    def _chat_stall_guard_ms(self) -> int:
        try:
            from pnn.llm.config_store import load_llm_config

            if load_llm_config().nsfw_enabled:
                return 600_000
        except Exception:
            pass
        return 90_000

    def _arm_stall_guard(self) -> None:
        self._stall_guard.setInterval(self._chat_stall_guard_ms())
        self._stall_guard.start()

    def _disarm_stall_guard(self) -> None:
        self._stall_guard.stop()

    def _mark_bubble_thinking(self) -> None:
        self._bubble_thinking = True
        self.bubble_changed.emit("…", False)

    def _clear_bubble_thinking(self) -> None:
        self._bubble_thinking = False

    def _show_bubble_fallback(self, turn: int) -> None:
        """TTS/翻译失败时：用已清洗的正文替换卡住的「…」。"""
        if turn != self._turn_id:
            return
        text = (self._display_answer_text or self._answer_text or "").strip()
        if not text:
            self._clear_bubble_thinking()
            self.bubble_changed.emit("", False)
            return
        self._clear_bubble_thinking()
        self._schedule_display_translate(
            text,
            turn,
            is_stream=False,
            force_display=True,
        )

    def _recover_stalled_ui(self) -> None:
        """长时间无进展时解除 loading / 气泡 … 卡住。"""
        if self._loading and _qthread_running(self._chat_worker):
            logger.debug("chat stall timeout, cancel")
            self.interrupt_current()
            self._emit_status("思考中…", False)
            return
        if self._loading:
            self._loading = False
            self.loading_changed.emit(False)
            self._clear_bubble_thinking()
            self.bubble_changed.emit("", False)
            self._emit_status("对话状态已恢复", True)
            return
        if self._seg_synth:
            logger.debug("tts synth stall, fallback to text bubble")
            self._seg_synth.clear()
            for i in range(len(self._seg_texts)):
                self._seg_failed.add(i)
            self.stop_audio()
            self._show_bubble_fallback(self._turn_id)
            self._flush_pending_memory()
            self.playback_finished.emit()
            self._sync_pipeline_status()
            return
        if self._bubble_thinking:
            logger.debug("bubble ellipsis stall, show text")
            self._show_bubble_fallback(self._turn_id)
            if not self._pipeline_active():
                self.playback_finished.emit()

    def set_voice_output_enabled(self, enabled: bool) -> None:
        self._voice_output_enabled = bool(enabled)
        if not self._voice_output_enabled:
            self.stop_audio(emit_finished=True)

    def set_text_only_mode(self, enabled: bool) -> None:
        """纯文字模式：跳过对话 TTS 合成/播放，保留 TTS 服务与其它预生成能力。"""
        self._text_only_mode = bool(enabled)
        if self._text_only_mode:
            self.stop_audio(emit_finished=True)

    def _tts_active_for_chat(self) -> bool:
        return self._voice_output_enabled and not self._text_only_mode

    def set_stream_bubble_output(self, enabled: bool) -> None:
        self._stream_bubble_output = bool(enabled)

    def _is_stale_turn(self, turn: int) -> bool:
        return turn != self._turn_id

    def _sync_pipeline_status(self, *, is_err: bool = False) -> None:
        """状态栏与终端日志对齐：播放优先于合成。"""
        if self._playback_active:
            self._emit_status("播放中…", is_err)
            return
        if self._seg_synth:
            n = len(self._seg_synth)
            if n > 0:
                self._emit_status(f"正在合成语音…（{n} 段进行中）", is_err)
            else:
                self._emit_status("正在合成语音…", is_err)
            return
        if self._play_queue:
            self._emit_status("等待播放…", is_err)
            return
        if not is_err:
            self._emit_status("就绪", False)
        self._refresh_voice_bubble_hint()

    def _refresh_voice_bubble_hint(self) -> None:
        """开启语音时：LLM/合成/等待播放阶段显示 …，播放中或分句进行中不覆盖正文。"""
        if not self._voice_output_enabled or self._playback_active:
            return
        if self._pipeline_active():
            return
        waiting = self._loading or bool(self._seg_synth)
        if waiting:
            self._mark_bubble_thinking()

    def _emit_status(self, msg: str, is_err: bool = False) -> None:
        if msg == self._last_status and is_err == self._last_status_err:
            return
        self._last_status = msg
        self._last_status_err = is_err
        self.status_changed.emit(msg, is_err)

    def _poll_mouth(self) -> None:
        self._try_flush_playback_bubble()
        v = self._lip.mouth_open_y()
        if abs(v - self._last_mouth) < 0.02:
            return
        self._last_mouth = v
        self._live2d.set_mouth_open(v)

    def _try_flush_playback_bubble(self) -> None:
        """口型有输出或短暂等待后再刷气泡，避免先出字后出声。"""
        pending = self._playback_bubble_pending
        if pending is None or not self._playback_active:
            return
        self._playback_bubble_wait_ticks += 1
        if self._lip.mouth_open_y() > 0.04 or self._playback_bubble_wait_ticks >= 4:
            text, turn, play_id, literal = pending
            self._playback_bubble_pending = None
            self._playback_bubble_wait_ticks = 0
            self._emit_playback_bubble(text, turn, play_id=play_id, literal=literal)

    def _clear_playback_bubble_pending(self) -> None:
        self._playback_bubble_pending = None
        self._playback_bubble_wait_ticks = 0

    def is_playing_audio(self) -> bool:
        return self._lip.playback_active()

    def _pipeline_active(self) -> bool:
        if not self._seg_texts:
            return False
        return (
            self._playback_active
            or bool(self._play_queue)
            or bool(self._seg_synth)
            or self._seg_play_idx < len(self._seg_texts)
        )

    def is_busy(self) -> bool:
        if self._loading:
            return True
        return self._pipeline_active()

    def perform_user_action(self, action_id: str) -> bool:
        """用户直接口令触发的即时动作（坐、点头等）。"""
        from pnn.pet.actions import ACTIONS, resolve_action_name

        name = resolve_action_name(action_id) or (action_id or "").strip()
        if not name or name not in ACTIONS:
            return False
        self._live2d.perform_action(name)
        if pet_console_verbose():
            print(f"[pet-ai] 用户口令动作: {name}", flush=True)
        return True

    def has_pending_voice_playback(self) -> bool:
        """是否仍有未播完的语音分句（合成中或排队中）。"""
        if not self._seg_texts:
            return False
        return (
            self._playback_active
            or bool(self._play_queue)
            or bool(self._seg_synth)
            or self._seg_play_idx < len(self._seg_texts)
        )

    def prepare(self) -> bool:
        if not self._api.health():
            self._emit_status("API 未启动 (8765)", True)
            return False
        return True

    def startup_greeting_played(self) -> bool:
        return self._startup_greeting_played

    def try_time_greeting(self) -> None:
        """每次启动按当前时段播放问候（优先本地 wav，无文件才后台合成）。"""
        if self.is_busy():
            return
        if not self._voice_output_enabled and not self._text_only_mode:
            return
        if self._startup_greeting_played:
            return
        if _qthread_running(self._time_greeting_worker):
            return
        try:
            from pnn.pet.presence.config import load_presence_config

            if not load_presence_config().time_greeting_enabled:
                logger.debug("跳过启动问候：日程中已关闭时段问候")
                return
        except Exception:
            pass
        from pnn.characters.reply_lang import active_reply_language
        from pnn.pet.time_greeting import (
            get_time_greeting,
            load_time_greeting_wav,
            time_greeting_character_id,
        )

        lang = active_reply_language()
        cid = time_greeting_character_id()
        display, _tts, slot = get_time_greeting(lang, char_id=cid)
        if self._text_only_mode:
            self._startup_greeting_played = True
            if (display or "").strip():
                self.bubble_changed.emit(display.strip(), False)
            return
        cached = load_time_greeting_wav(slot, lang, char_id=cid)
        if cached:
            self._play_time_greeting(display, cached)
            return
        worker = _TimeGreetingWorker(
            self._api,
            slot.value,
            lang,
            display,
            char_id=cid,
            parent=self,
        )
        self._time_greeting_worker = worker
        worker.finished_ok.connect(self._on_time_greeting_wav)
        worker.failed.connect(self._on_time_greeting_failed)
        worker.finished.connect(
            lambda w=worker: self._clear_time_greeting_worker(w),
        )
        _start_thread(worker)

    def _clear_time_greeting_worker(self, worker: _TimeGreetingWorker) -> None:
        if self._time_greeting_worker is worker:
            self._time_greeting_worker = None

    def _on_time_greeting_wav(self, wav: bytes, display: str) -> None:
        self._play_time_greeting(display, wav)

    def _on_time_greeting_failed(self, err: str) -> None:
        logger.warning("时段问候语音: %s", err)
        from pnn.characters.reply_lang import active_reply_language
        from pnn.pet.time_greeting import get_time_greeting, time_greeting_character_id

        display, _tts, _slot = get_time_greeting(
            active_reply_language(),
            char_id=time_greeting_character_id(),
        )
        self._startup_greeting_played = True
        if (display or "").strip():
            self.bubble_changed.emit(display.strip(), False)

    def _play_time_greeting(self, display: str, wav: bytes) -> None:
        self._startup_greeting_played = True
        text = (display or "").strip()
        if text:
            self.bubble_changed.emit(text, False)
        if not self._tts_active_for_chat():
            self.playback_finished.emit()
            return
        if not wav:
            return
        self._play_audio(
            text,
            wav,
            on_end=lambda: self.playback_finished.emit(),
            bubble_literal=True,
        )

    def announce_screenshot_recognized(
        self,
        image_base64: str = "",
        image_mime: str = "image/png",
    ) -> None:
        """附截图：气泡固定提示 → 本地/缓存 TTS 提示语 → 识图 → TTS 摘要 → 结束关气泡。"""
        from pnn.characters.reply_lang import active_reply_language
        from pnn.llm.vision_client import vision_configured
        from pnn.pet.screenshot_hint import (
            get_screenshot_hint,
            load_screenshot_hint_wav,
        )
        from pnn.tts.character_layout import active_character_id

        lang = active_reply_language()
        display, _tts = get_screenshot_hint(lang, char_id=active_character_id())
        img = (image_base64 or "").strip()
        self._pending_screenshot_analysis = ""
        self._screenshot_flow_active = True
        self._screenshot_hint_played = False
        self._screenshot_analysis_played = False
        self._screenshot_analysis_tts_text = ""
        self._screenshot_vision_pending = bool(img and vision_configured())
        self._screenshot_hint_display = display
        self._screenshot_vision_error = ""

        if self._voice_output_enabled:
            self.bubble_changed.emit("…", False)
        else:
            self.bubble_changed.emit(display, False)
        self._play_screenshot_hint_tts(lang, load_screenshot_hint_wav(lang))

        if self._screenshot_vision_pending:
            if _qthread_running(self._screenshot_vision_worker):
                return
            self._screenshot_vision_worker = None
            worker = _ScreenshotVisionWorker(self._api, img, image_mime, parent=self)
            self._screenshot_vision_worker = worker
            worker.finished_ok.connect(
                lambda analysis, lg=lang: self._on_screenshot_vision_ok(analysis, lg),
            )
            worker.failed.connect(
                lambda err, lg=lang: self._on_screenshot_vision_fail(err, lg),
            )
            worker.finished.connect(
                lambda w=worker: self._clear_screenshot_vision_worker(w),
            )
            _start_thread(worker)
        elif img and not vision_configured():
            logger.warning(
                "未配置视觉模型，仅显示截图提示。请在 .env 设置 DASHSCOPE_API_KEY 与 DASHSCOPE_VL_MODEL"
            )

    def _clear_screenshot_vision_worker(self, worker: _ScreenshotVisionWorker) -> None:
        if self._screenshot_vision_worker is worker:
            self._screenshot_vision_worker = None

    def _clear_screenshot_hint_worker(self, worker: _ScreenshotHintWorker) -> None:
        if self._screenshot_hint_worker is worker:
            self._screenshot_hint_worker = None

    def _clear_screenshot_analysis_tts_worker(self, worker: _ScreenshotAnalysisTtsWorker) -> None:
        if self._screenshot_analysis_tts_worker is worker:
            self._screenshot_analysis_tts_worker = None

    def _show_screenshot_hint_bubble(self) -> None:
        body = (self._screenshot_hint_display or "").strip()
        err = (self._screenshot_vision_error or "").strip()
        if err and body:
            body = f"{body}\n（{err}）"
        elif err:
            body = f"（{err}）"
        if body:
            self.bubble_changed.emit(body, False)

    def _on_screenshot_vision_ok(self, analysis: str, lang: str) -> None:
        self._screenshot_vision_pending = False
        text = (analysis or "").strip()
        self._pending_screenshot_analysis = text
        self._screenshot_analysis_tts_text = text
        self.screenshot_analysis_ready.emit(text)
        if text:
            from pnn.pet.screenshot_hint import format_screenshot_analysis_bubble

            print(
                f"[pet-ai] 截图识图摘要（{len(text)} 字）\n"
                f"{format_screenshot_analysis_bubble(text)}",
                flush=True,
            )
        self._try_start_analysis_tts()

    def _on_screenshot_vision_fail(self, err: str, lang: str) -> None:
        self._screenshot_vision_pending = False
        short = (err or "识图失败").replace("\n", " ").strip()
        if len(short) > 120:
            short = short[:117] + "…"
        self._screenshot_vision_error = short
        self.screenshot_analysis_ready.emit("")
        logger.warning("截图识图: %s", err)
        if self._screenshot_hint_played:
            self._show_screenshot_hint_bubble()
        self._maybe_finish_screenshot_flow()

    def _try_start_analysis_tts(self) -> None:
        if not self._screenshot_flow_active or self._screenshot_analysis_played:
            return
        if not self._screenshot_hint_played:
            return
        text = (self._screenshot_analysis_tts_text or "").strip()
        if not text:
            self._maybe_finish_screenshot_flow()
            return
        worker = self._screenshot_analysis_tts_worker
        if _qthread_running(worker):
            return
        from pnn.characters.reply_lang import active_reply_language
        from pnn.pet.screenshot_hint import format_analysis_segments

        lang = active_reply_language()
        if not format_analysis_segments(text, lang):
            self._screenshot_analysis_played = True
            self._maybe_finish_screenshot_flow()
            return
        worker = _ScreenshotAnalysisTtsWorker(self._api, text, lang, parent=self)
        self._screenshot_analysis_tts_worker = worker
        worker.finished_ok.connect(self._on_screenshot_analysis_tts_segments)
        worker.failed.connect(self._on_screenshot_analysis_tts_failed)
        worker.finished.connect(
            lambda w=worker: self._clear_screenshot_analysis_tts_worker(w),
        )
        _start_thread(worker)

    def _on_screenshot_analysis_tts_failed(self, err: str) -> None:
        logger.warning("识图摘要语音: %s", err)
        self._screenshot_analysis_played = True
        from pnn.pet.screenshot_hint import format_screenshot_analysis_bubble

        text = (self._screenshot_analysis_tts_text or "").strip()
        if text:
            self.bubble_changed.emit(format_screenshot_analysis_bubble(text), False)
        self._maybe_finish_screenshot_flow()

    def _on_screenshot_analysis_tts_segments(self, segments: object) -> None:
        items: list[tuple[str, bytes]] = list(segments)  # type: ignore[arg-type]
        if not items:
            self._screenshot_analysis_played = True
            self._maybe_finish_screenshot_flow()
            return
        for i, (display, wav) in enumerate(items):
            is_last = i == len(items) - 1
            line = (display or "").strip()

            def _on_end(*, last: bool = is_last) -> None:
                if last:
                    self._maybe_finish_screenshot_flow()

            self._play_audio(line, wav, on_end=_on_end, bubble_literal=True)
        self._screenshot_analysis_played = True

    def _play_screenshot_hint_tts(self, lang: str, cached: bytes | None) -> None:
        if self.is_busy() and not self._screenshot_flow_active:
            return
        if cached:
            self._play_screenshot_flow_audio(
                cached,
                bubble_text=self._screenshot_hint_display,
                is_hint=True,
            )
            return
        if _qthread_running(self._screenshot_hint_worker):
            return
        worker = _ScreenshotHintWorker(self._api, lang, parent=self)
        self._screenshot_hint_worker = worker
        worker.finished_ok.connect(self._on_screenshot_hint_wav)
        worker.failed.connect(self._on_screenshot_hint_tts_failed)
        worker.finished.connect(
            lambda w=worker: self._clear_screenshot_hint_worker(w),
        )
        _start_thread(worker)

    def _on_screenshot_hint_tts_failed(self, err: str) -> None:
        logger.warning("截图提示语音: %s", err)
        self._screenshot_hint_played = True
        self._show_screenshot_hint_bubble()
        self._try_start_analysis_tts()

    def _on_screenshot_hint_wav(self, wav: bytes) -> None:
        if self.is_busy() and not self._screenshot_flow_active:
            return
        self._play_screenshot_flow_audio(
            wav,
            bubble_text=self._screenshot_hint_display,
            is_hint=True,
        )

    def _play_screenshot_flow_audio(
        self,
        wav: bytes,
        *,
        bubble_text: str = "",
        is_hint: bool,
    ) -> None:
        def on_end() -> None:
            if is_hint and self._screenshot_flow_active:
                self._screenshot_hint_played = True
                self._try_start_analysis_tts()
            self._maybe_finish_screenshot_flow()

        self._play_audio(bubble_text, wav, on_end=on_end, bubble_literal=True)

    def _maybe_finish_screenshot_flow(self) -> None:
        self._pump_play_queue()
        if self._playback_active or self._play_queue:
            return
        if not self._screenshot_flow_active:
            self.playback_finished.emit()
            return
        if not self._screenshot_hint_played:
            return
        if self._screenshot_vision_pending:
            return
        pending_analysis = (self._screenshot_analysis_tts_text or "").strip()
        if pending_analysis:
            worker = self._screenshot_analysis_tts_worker
            if _qthread_running(worker):
                return
            if not self._screenshot_analysis_played:
                self._try_start_analysis_tts()
                return
            if self._playback_active or self._play_queue:
                return
        self._screenshot_flow_active = False
        self.playback_finished.emit()

    def _ensure_expression_catalog(self) -> None:
        try:
            from pnn.characters.service import character_pack_service

            character_pack_service.ensure_migrated()
            cid = character_pack_service.get_active_id()
        except Exception:
            cid = ""
        if self._expr_names is not None and self._expr_prompt_char_id == cid:
            return
        self._expr_prompt_char_id = cid
        self._expr_names = discover_expression_names()
        self._expr_available = set(self._expr_names)
        expr_prompt = build_llm_expression_instruction(self._expr_names)
        action_prompt = build_llm_action_instruction()
        parts = [action_prompt, expr_prompt]
        try:
            from pnn.characters.service import character_pack_service
            from pnn.tts.voice_library import build_llm_emotion_tag_instruction

            character_pack_service.ensure_migrated()
            cid = character_pack_service.get_active_id()
            emo = build_llm_emotion_tag_instruction(cid)
            coherence = build_coherence_prompt_addon(cid)
            if coherence:
                parts.insert(0, coherence)
            if emo:
                parts.insert(0, emo)
        except Exception:
            pass
        self._pet_expr_prompt = "\n\n".join(parts)

    def _trim_history(self) -> None:
        if len(self._history) > MAX_HISTORY_MESSAGES:
            del self._history[: len(self._history) - MAX_HISTORY_MESSAGES]

    def _reset_tts_state(self) -> None:
        self._translate_worker = None
        self._stream_translate_seq += 1
        self._stream_translate_worker = None
        self._pending_stream_translate = ""
        self._bubble_translate_seq += 1
        self._play_queue.clear()
        self._seg_texts.clear()
        self._seg_display_zh.clear()
        self._seg_exprs.clear()
        self._seg_tts_tags.clear()
        self._seg_audio.clear()
        self._seg_actions.clear()
        self._seg_synth.clear()
        self._seg_failed.clear()
        self._seg_seen.clear()
        self._seg_play_idx = 0
        self._seg_chunk_remain.clear()
        self._tts_spoken_offset = 0
        self._stream_last_expr = None
        self._stream_last_emotion_tag = None
        self._raw_answer_text = ""
        self._tts_pending_text = ""
        self._tts_pending_action = None
        self._tts_pending_emotion = ""
        self._tts_batches_flushed = 0

    def _flush_tts_pending(self) -> None:
        """将缓冲中的同情绪多句合并为一条队列项（一次合成线程，内部可再切分）。"""
        piece = self._tts_pending_text.strip()
        if not piece:
            return
        expr = self._tts_pending_expr or _default_expression()
        action = self._tts_pending_action
        emotion = self._tts_pending_emotion or None
        self._tts_pending_text = ""
        self._tts_pending_action = None
        self._tts_pending_emotion = ""
        self._tts_batches_flushed += 1
        preview = piece.replace("\n", " ")[:48]
        log_tts("批次", f"#{self._tts_batches_flushed} [{emotion or '-'}] {preview}")
        self._enqueue_seg(piece, expr, action, emotion)

    def _seg_piece_redundant(self, piece: str) -> bool:
        """是否已被更长分句覆盖或完全相同。"""
        if not piece or piece in self._seg_seen:
            return True
        for ex in self._seg_texts:
            if ex == piece or piece in ex:
                return True
        return False

    def _fix_erroneous_merged_segs(self, piece: str) -> None:
        """作废「把多句粘在一起、又以本句为前缀」且尚未合成的长分句。"""
        for i, ex in enumerate(self._seg_texts):
            if i < self._seg_play_idx:
                continue
            if i in self._seg_synth or i in self._seg_audio or i in self._seg_failed:
                continue
            if ex.startswith(piece) and len(ex) > len(piece):
                self._seg_failed.add(i)
                self._seg_seen.discard(ex)
                log_tts(
                    "分句",
                    f"作废误合并 #{i + 1}（{len(ex)} 字），改按句登记",
                )

    def _drain_tagged_tts_from_offset(self, full: str) -> None:
        """从 spoken_offset 起按句切分并入队（流式/结束时补漏）。"""
        tts_buf = self._tts_stream_buffer(full)
        while self._tts_spoken_offset < len(tts_buf):
            chunks, new_off, self._stream_last_expr, self._stream_last_emotion_tag = (
                pull_tagged_tts_chunks(
                    tts_buf,
                    self._tts_spoken_offset,
                    available=self._expr_available,
                    last_expr=self._stream_last_expr,
                    last_emotion_tag=self._stream_last_emotion_tag,
                )
            )
            if not chunks and new_off <= self._tts_spoken_offset:
                break
            for expr, piece, action, tts_tag in chunks:
                self._enqueue_tts(piece, expr, action, tts_tag)
            if new_off <= self._tts_spoken_offset:
                break
            self._tts_spoken_offset = new_off

    def _finalize_tts_from_full(self, full: str) -> None:
        """流式结束后：先按句 drain，再仅对无句末标点的尾段 pull_final。"""
        tts_buf = self._tts_stream_buffer(full)
        self._flush_tts_pending()
        self._drain_tagged_tts_from_offset(full)
        tail_pack, self._tts_spoken_offset, self._stream_last_expr, self._stream_last_emotion_tag = (
            pull_final_tagged_chunk(
                tts_buf,
                self._tts_spoken_offset,
                available=self._expr_available,
                last_expr=self._stream_last_expr,
                last_emotion_tag=self._stream_last_emotion_tag,
            )
        )
        if tail_pack:
            expr, piece, action, tts_tag = tail_pack
            if piece and not self._seg_piece_redundant(piece):
                self._enqueue_tts(piece, expr, action, tts_tag)
        self._flush_tts_pending()
        self._reconcile_tts_from_full(full)

    def _reconcile_tts_from_full(self, full: str) -> None:
        """流式结束后补登记漏掉的分句（保证整段回复都会进入 TTS 队列）。"""
        tts_buf = self._tts_stream_buffer(full)
        offset = 0
        expr = self._stream_last_expr
        emo = self._stream_last_emotion_tag
        added = 0
        while offset < len(tts_buf):
            chunks, new_off, expr, emo = pull_tagged_tts_chunks(
                tts_buf,
                offset,
                available=self._expr_available,
                last_expr=expr,
                last_emotion_tag=emo,
            )
            if not chunks and new_off <= offset:
                break
            for e, piece, action, tag in chunks:
                p = piece.strip()
                if p and not self._seg_piece_redundant(p):
                    self._enqueue_seg(p, e, action, tag)
                    added += 1
            offset = new_off
        tail_pack, _off, expr, emo = pull_final_tagged_chunk(
            tts_buf,
            offset,
            available=self._expr_available,
            last_expr=expr,
            last_emotion_tag=emo,
        )
        if tail_pack:
            e, piece, action, tag = tail_pack
            p = piece.strip()
            if p and not self._seg_piece_redundant(p):
                self._enqueue_seg(p, e, action, tag)
                added += 1
        if added:
            log_tts("批次", f"补登记 {added} 个分句")

    def _invalidate_bubble_translates(self) -> None:
        self._bubble_translate_seq += 1
        self._stream_translate_seq += 1
        self._playback_play_id += 1

    def _begin_new_turn(self) -> None:
        """新一轮用户/主动对话：作废在途翻译，避免上一句译文闪入本句。"""
        self._flush_pending_memory(allow_stale=True)
        self._turn_id += 1
        self._invalidate_bubble_translates()

    def interrupt_current(self) -> None:
        self._flush_pending_memory(allow_stale=True)
        self._turn_id += 1
        self._stream_cancel.set()
        self._invalidate_bubble_translates()
        self._clear_memory_extract_state()
        was_loading = self._loading
        self.stop_audio()
        self._reset_tts_state()
        if was_loading and self._history and self._history[-1].role == "user":
            self._history.pop()
        if was_loading:
            self._loading = False
            self.loading_changed.emit(False)
            self._disarm_stall_guard()
            self._clear_bubble_thinking()
            self.bubble_changed.emit("", False)

    def send_proactive(self, system_context: str, *, trigger_kind: str = "") -> None:
        """系统触发的主动搭话（不写入用户历史、不在输入框展示）。"""
        ctx = (system_context or "").strip()
        if not ctx:
            return
        if self.is_busy():
            return
        from pnn.memory.sanitize import is_schedule_proactive_context
        from pnn.llm.routing import nsfw_blocks_presence_proactive

        is_schedule = is_schedule_proactive_context(ctx)
        kind = (trigger_kind or "").strip()
        if not is_schedule and nsfw_blocks_presence_proactive(kind):
            return
        self._proactive_is_schedule = is_schedule
        self._proactive_trigger_kind = kind
        self._proactive_turn = True
        self._proactive_context = ctx
        self._begin_new_turn()
        label = PROACTIVE_TRIGGER_LABELS.get(self._proactive_trigger_kind, "主动搭话")
        self._emit_status(
            "日程提醒…" if self._proactive_is_schedule else f"{label}…",
            False,
        )
        self._start_llm_turn(
            "（请根据系统背景主动开口，不要复述系统文本）",
            history_snapshot=list(self._history),
            append_user_history=False,
            presence_prefix=ctx,
        )

    def send_message(
        self,
        text: str,
        *,
        interrupt: bool = False,
        image_base64: str = "",
        image_mime: str = "image/png",
        image_analysis: str = "",
        presence_prefix: str = "",
    ) -> None:
        msg = text.strip()
        img = (image_base64 or "").strip()
        if not msg and not img:
            return
        if self.is_busy():
            if not interrupt:
                return
            self.interrupt_current()
        else:
            self._begin_new_turn()
        self._proactive_turn = False
        self._proactive_is_schedule = False

        # 切换角色时清空对话历史，避免语言/人设污染
        try:
            from pnn.characters.service import character_pack_service

            cur_char = character_pack_service.get_active_id()
            if cur_char and cur_char != self._last_char_id:
                self._history.clear()
                self._last_char_id = cur_char
        except Exception:
            pass

        hist_text = msg if msg else "（请根据附图搜索下载）"
        if img:
            hist_text = f"{hist_text} [附图]"
        self._history.append(ChatMessage(role="user", content=hist_text))
        self._last_user_msg = hist_text
        self._trim_history()

        try:
            from pnn.system_control.direct import schedule_qq_music_focus_on_topic

            schedule_qq_music_focus_on_topic(msg)
        except Exception:
            pass

        self._start_llm_turn(
            msg,
            history_snapshot=self._history[:-1],
            append_user_history=False,
            presence_prefix=presence_prefix,
            image_base64=img,
            image_mime=image_mime,
            image_analysis=(image_analysis or self._pending_screenshot_analysis or "").strip(),
        )
        self._pending_screenshot_analysis = ""

    def _merge_presence_prompt(self, presence_prefix: str) -> str | None:
        prefix = (presence_prefix or "").strip()
        base = (self._pet_expr_prompt or "").strip()
        if prefix and base:
            return f"{prefix}\n\n{base}"
        return prefix or base or None

    def _start_llm_turn(
        self,
        message: str,
        *,
        history_snapshot: list[ChatMessage],
        append_user_history: bool,
        presence_prefix: str = "",
        image_base64: str = "",
        image_mime: str = "image/png",
        image_analysis: str = "",
    ) -> None:
        turn = self._turn_id
        self._stream_cancel.clear()
        self._loading = True
        self._answer_text = ""
        self._display_answer_text = ""
        self._raw_answer_text = ""
        self._reset_tts_state()
        self.loading_changed.emit(True)
        self._arm_stall_guard()
        if self._voice_output_enabled:
            self._mark_bubble_thinking()
        else:
            self.bubble_changed.emit("", False)
        self._last_delta_len = 0
        self._last_bubble_emit_snapshot = ""
        self._delta_throttle.restart()
        log_llm_stream_reset()
        self._emit_status("思考中…", False)
        self._ensure_expression_catalog()

        from pnn.pet.api_client import _sanitize_chat_history

        history_snapshot = _sanitize_chat_history(history_snapshot)

        worker = _ChatWorker(
            self._api,
            message,
            history_snapshot,
            stream_deltas=True,
            pet_expression_prompt=self._merge_presence_prompt(presence_prefix),
            image_base64=image_base64,
            image_mime=image_mime or "image/png",
            image_analysis=image_analysis,
            cancel=self._stream_cancel,
            defer_memory=self._proactive_turn or self._voice_output_enabled,
            internal_turn=self._proactive_turn,
            parent=self,
        )
        self._chat_worker = worker
        worker.failed.connect(lambda err: self._on_chat_failed(err, turn, append_user_history))
        worker.finished_ok.connect(lambda full: self._on_chat_done(full, turn))
        worker.finished.connect(lambda w=worker: self._clear_chat_worker_ref(w))
        worker.delta_changed.connect(
            lambda full: self._on_chat_delta(full, turn),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.agent_status.connect(
            lambda s: self._emit_status(s, False),
            Qt.ConnectionType.QueuedConnection,
        )
        _start_thread(worker)

    def _clear_chat_worker_ref(self, worker: _ChatWorker) -> None:
        if self._chat_worker is worker:
            self._chat_worker = None

    def _clear_stream_translate_worker_ref(self, worker: _TranslateWorker) -> None:
        if self._stream_translate_worker is worker:
            self._stream_translate_worker = None

    def _reply_bubble_text(self, raw: str) -> str:
        """气泡通道：去标签 + 去记忆元叙述。"""
        from pnn.pet.reply_text import bubble_text_for_reply

        body = (raw or "").strip()
        if not body:
            return ""
        return bubble_text_for_reply(body) or strip_expression_tags(body).strip()

    def _tts_stream_buffer(self, full: str) -> str:
        from pnn.pet.bilingual_reply import speech_buffer_for_tts

        return speech_buffer_for_tts(full)

    def _assistant_history_text(self, full: str) -> str:
        from pnn.pet.bilingual_reply import speech_text_for_history

        return strip_expression_tags(speech_text_for_history(full)).strip()

    def _assistant_storage_text(self, full: str) -> str:
        return strip_expression_tags(full).strip()

    def _display_for_voice_log(self, seg_text: str, seg_index: int) -> str:
        """TTS 终端：每句显示对应中文（【中文】块按句对齐）。"""
        if 0 <= seg_index < len(self._seg_display_zh):
            zh = (self._seg_display_zh[seg_index] or "").strip()
            if zh:
                return zh
        from pnn.pet.bilingual_reply import chinese_display_for_segment

        return chinese_display_for_segment(
            self._raw_answer_text,
            seg_text,
            seg_index=seg_index,
        )

    def _on_chat_delta(self, full: str, turn: int) -> None:
        if turn != self._turn_id:
            return
        from pnn.pet.expression_tags import normalize_pet_output_tags

        full = normalize_pet_output_tags(full, available=self._expr_available or set())
        self._raw_answer_text = full
        self._answer_text = strip_expression_tags(full)
        self._display_answer_text = self._reply_bubble_text(full)
        if turn <= self._chat_tts_finalized_turn:
            return
        chunks, self._tts_spoken_offset, self._stream_last_expr, self._stream_last_emotion_tag = (
            pull_tagged_tts_chunks(
                self._tts_stream_buffer(full),
                self._tts_spoken_offset,
                available=self._expr_available,
                last_expr=self._stream_last_expr,
                last_emotion_tag=self._stream_last_emotion_tag,
            )
        )
        for expr, piece, action, tts_tag in chunks:
            self._enqueue_tts(piece, expr, action, tts_tag)
        # 开启语音时气泡随播放逐句更新，流式阶段不刷整段回复（避免全文闪现后消失）
        if (
            self._stream_bubble_output
            and self._display_answer_text
            and not self._voice_output_enabled
        ):
            elapsed = self._delta_throttle.elapsed()
            if elapsed > 200 and self._display_answer_text != self._last_bubble_emit_snapshot:
                self._last_bubble_emit_snapshot = self._display_answer_text
                self._delta_throttle.restart()
                self._schedule_display_translate(
                    self._display_answer_text, turn, bubble_seq=None, is_stream=True
                )

    def _on_chat_failed(self, err: str, turn: int, append_user_history: bool = True) -> None:
        if turn != self._turn_id:
            return
        self._loading = False
        self.loading_changed.emit(False)
        self._disarm_stall_guard()
        self._clear_bubble_thinking()
        self.bubble_changed.emit("", False)
        if (
            not self._proactive_turn
            and self._history
            and self._history[-1].role == "user"
        ):
            self._history.pop()
        self._proactive_turn = False
        self._emit_status(f"对话: {err}", True)
        log_llm_stream_abort()
        print(f"[pet-llm] 失败: {err}", flush=True)

    def _on_chat_done(self, full: str, turn: int) -> None:
        if self._is_stale_turn(turn):
            if self._loading and not _qthread_running(self._chat_worker):
                self._loading = False
                self.loading_changed.emit(False)
            return
        self._loading = False
        self.loading_changed.emit(False)
        self._disarm_stall_guard()
        self._raw_answer_text = full
        speech_clean = self._assistant_history_text(full)
        storage_clean = self._assistant_storage_text(full)
        display = self._reply_bubble_text(full)
        self._answer_text = speech_clean
        self._display_answer_text = display
        if speech_clean:
            self._history.append(ChatMessage(role="assistant", content=speech_clean))
            self._trim_history()
        streamed = log_llm_stream_finish(storage_clean)
        # 开语音时按句 [pet-tts] 输出中文；关语音且未流式打印时打整段 [pet-ai]
        if not self._voice_output_enabled and not streamed:
            log_ai_reply(full)
        proactive = self._proactive_turn
        proactive_schedule = self._proactive_is_schedule
        proactive_kind = self._proactive_trigger_kind
        self._proactive_turn = False
        self._proactive_is_schedule = False
        self._proactive_trigger_kind = ""
        proactive_ctx = self._proactive_context
        if proactive:
            self._proactive_context = ""
        user_for_turn = "" if proactive else self._last_user_msg
        if proactive and storage_clean.strip():
            from pnn.memory.sanitize import proactive_memory_user_line

            user_line = proactive_memory_user_line(proactive_ctx)
            if proactive_schedule:
                if self._voice_output_enabled:
                    self._defer_memory_turn(
                        user_line, storage_clean, turn, extract_events=False
                    )
                else:
                    self._notify_memory_turn(
                        user_line,
                        storage_clean,
                        turn=turn,
                        force_skip_extraction=True,
                    )
            from pnn.pet.reply_text import terminal_text_for_reply

            preview = terminal_text_for_reply(full) or storage_clean.replace("\n", " ")[:200]
            if proactive_schedule:
                print(f"[pet-schedule] 到点提醒: {preview}", flush=True)
            else:
                label = PROACTIVE_TRIGGER_LABELS.get(proactive_kind, "主动搭话")
                print(f"[pet-presence] {label}: {preview}", flush=True)
        elif self._voice_output_enabled and storage_clean.strip():
            self._defer_memory_turn(self._last_user_msg, storage_clean, turn)
        elif not proactive:
            self._notify_memory_turn(self._last_user_msg, storage_clean)
        if storage_clean.strip():
            self.turn_completed.emit(user_for_turn, storage_clean)

        if not storage_clean.strip():
            self._clear_bubble_thinking()
            self.bubble_changed.emit("", False)

        if not self._tts_active_for_chat():
            if self._stream_bubble_output and self._display_answer_text:
                self._schedule_display_translate(
                    self._display_answer_text, turn, is_stream=False
                )
            elif proactive and self._display_answer_text:
                self._schedule_display_translate(
                    self._display_answer_text, turn, is_stream=False
                )
            elif self._display_answer_text:
                self._schedule_display_translate(
                    self._display_answer_text, turn, is_stream=False
                )
            self._sync_pipeline_status()
            self.playback_finished.emit()
            return

        # 语音模式：作废流式阶段未完成的翻译，保持「…」直至首句播放
        self._bubble_translate_seq += 1
        self._stream_translate_seq += 1
        if speech_clean.strip():
            self._mark_bubble_thinking()

        has_tts = bool(speech_clean.strip())
        if has_tts:
            self._finalize_tts_from_full(full)
            n_seg = len(self._seg_texts)
            if n_seg:
                log_tts("批次", f"本轮共 {n_seg} 个分句待播")
            self._chat_tts_finalized_turn = turn
            self._pump_seg_play()
            self._pump_seg_synth()
            self._arm_stall_guard()
        if not self._pipeline_active():
            self._sync_pipeline_status()
            if has_tts and speech_clean.strip() and not self._seg_texts:
                log_tts("失败", "语音合成未产出可播放音频，改为仅显示文字")
                if turn == self._turn_id:
                    self._show_bubble_fallback(turn)
                self._flush_pending_memory()
                self.playback_finished.emit()
            elif not has_tts:
                self._clear_bubble_thinking()
                self._flush_pending_memory()
                self.playback_finished.emit()
            # 仍有分句待播/待合成时：勿在此处 playback_finished，避免气泡提前“结束”卡住

    def _defer_memory_turn(
        self,
        user_message: str,
        assistant_reply: str,
        turn: int,
        *,
        extract_events: bool = True,
    ) -> None:
        """语音模式：流式结束即后台提取 [event]；[dialogue] 等 TTS 播完再写。"""
        self._flush_pending_memory(allow_stale=True)
        self._pending_memory_user = (user_message or "").strip()
        self._pending_memory_reply = (assistant_reply or "").strip()
        self._pending_memory_turn_id = turn
        with self._memory_extract_lock:
            self._pending_memory_extracted = None
            self._pending_memory_extract_done = False
            self._pending_memory_extract_turn_id = turn
        if not extract_events:
            with self._memory_extract_lock:
                self._pending_memory_extract_done = True
                self._pending_memory_extracted = None
            logger.debug("流式结束，待语音结束后写入日程提醒 [dialogue]…")
            return
        logger.debug("流式结束，后台提取记忆 [event]…")
        self._start_memory_event_prefetch(user_message, assistant_reply, turn)

    def _start_memory_event_prefetch(
        self, user_message: str, assistant_reply: str, turn: int
    ) -> None:
        def _run() -> None:
            try:
                from pnn.memory.service import memory_service

                history = [
                    {"role": m.role, "content": m.content} for m in self._history[:-1]
                ]
                parsed = memory_service.extract_turn_events(
                    user_message, assistant_reply, history
                )
                with self._memory_extract_lock:
                    if turn not in (self._pending_memory_turn_id, self._turn_id):
                        return
                    self._pending_memory_extracted = parsed
                    self._pending_memory_extract_done = True
                if parsed and parsed.get("save"):
                    logger.debug(
                        "DeepSeek 已提取记忆 [event]（待语音结束后落库）"
                    )
            except Exception as exc:
                logger.warning("后台 [event] 提取失败: %s", exc)

        threading.Thread(
            target=_run, daemon=True, name="pet-memory-extract"
        ).start()

    def _clear_memory_extract_state(self) -> None:
        with self._memory_extract_lock:
            self._pending_memory_extracted = None
            self._pending_memory_extract_done = False
            self._pending_memory_extract_turn_id = 0

    def _clear_pending_memory(self) -> None:
        self._pending_memory_user = ""
        self._pending_memory_reply = ""
        self._pending_memory_turn_id = 0
        self._clear_memory_extract_state()

    def _flush_pending_memory(self, *, allow_stale: bool = False) -> None:
        user = self._pending_memory_user.strip()
        reply = self._pending_memory_reply.strip()
        turn = self._pending_memory_turn_id
        with self._memory_extract_lock:
            pre_extracted = self._pending_memory_extracted
            extract_done = self._pending_memory_extract_done
            extract_turn = self._pending_memory_extract_turn_id
        self._pending_memory_user = ""
        self._pending_memory_reply = ""
        self._pending_memory_turn_id = 0
        if not user or not reply or not turn:
            return
        if turn != self._turn_id and not allow_stale:
            self._pending_memory_user = user
            self._pending_memory_reply = reply
            self._pending_memory_turn_id = turn
            with self._memory_extract_lock:
                self._pending_memory_extracted = pre_extracted
                self._pending_memory_extract_done = extract_done
                self._pending_memory_extract_turn_id = extract_turn
            return
        logger.debug("语音已结束，开始写入记忆库…")
        self._notify_memory_turn(
            user,
            reply,
            turn=turn,
            pre_extracted=pre_extracted,
            extract_done=extract_done,
            extract_turn=extract_turn,
        )

    def _notify_memory_turn(
        self,
        user_message: str,
        assistant_reply: str,
        *,
        turn: int = 0,
        pre_extracted: dict | None = None,
        extract_done: bool = False,
        extract_turn: int = 0,
        force_skip_extraction: bool = False,
    ) -> None:
        """桌宠侧触发记忆写入（与 API 服务端互为备份，写入函数内会去重）。"""
        user_message = (user_message or "").strip()
        assistant_reply = (assistant_reply or "").strip()
        if not user_message or not assistant_reply:
            return

        def _run() -> None:
            if not self._memory_turn_lock.acquire(blocking=False):
                logger.debug("跳过记忆写入：上一轮仍在处理")
                return
            try:
                from pnn.memory.service import memory_service

                history = [
                    {"role": m.role, "content": m.content} for m in self._history[:-1]
                ]
                use_pre = pre_extracted
                skip_extract = force_skip_extraction
                if not skip_extract and turn and extract_turn == turn and extract_done:
                    skip_extract = True
                elif not skip_extract and turn and extract_turn == turn and not extract_done:
                    deadline = time.monotonic() + 45.0
                    while time.monotonic() < deadline:
                        with self._memory_extract_lock:
                            if (
                                self._pending_memory_extract_done
                                and self._pending_memory_extract_turn_id == turn
                            ):
                                use_pre = self._pending_memory_extracted
                                skip_extract = True
                                break
                        time.sleep(0.25)
                memory_service.after_conversation_turn(
                    user_message,
                    assistant_reply,
                    history,
                    pre_extracted=use_pre,
                    skip_extraction=skip_extract,
                )
            except Exception as exc:
                logger.warning("记忆写入失败: %s", exc)
            finally:
                if extract_turn:
                    with self._memory_extract_lock:
                        if self._pending_memory_extract_turn_id == extract_turn:
                            self._pending_memory_extracted = None
                            self._pending_memory_extract_done = False
                            self._pending_memory_extract_turn_id = 0
                self._memory_turn_lock.release()

        threading.Thread(target=_run, daemon=True, name="pet-memory-turn").start()

    def _translate_enabled(self) -> bool:
        try:
            from pnn.translate.service import translate_service

            return translate_service.display_translation_for_bubble()
        except Exception:
            return False

    def _emit_playback_bubble(
        self,
        text: str,
        turn: int,
        *,
        play_id: int,
        literal: bool = False,
    ) -> None:
        """音频已开始播放后再刷新气泡（剥离标签，可选译成中文）。"""
        from pnn.pet.reply_text import bubble_text_for_reply

        piece = (text or "").strip() if literal else bubble_text_for_reply(text)
        if (
            not piece
            or self._is_stale_turn(turn)
            or not self._playback_active
            or play_id != self._playback_play_id
        ):
            return
        self._stream_translate_seq += 1
        self._stream_translate_worker = None
        if literal or self._screenshot_flow_active:
            self._bubble_translate_seq += 1
            seq = self._bubble_translate_seq
            self._emit_bubble_if_current(
                piece,
                turn,
                bubble_seq=seq,
                play_id=play_id,
                is_stream=False,
            )
            return
        self._schedule_display_translate(
            piece,
            turn,
            play_id=play_id,
            is_stream=False,
        )

    def _enqueue_tts(
        self,
        text: str,
        expression: str | None = None,
        action: str | None = None,
        tts_emotion_tag: str | None = None,
    ) -> None:
        if not self._tts_active_for_chat():
            return
        piece = text.strip()
        if not piece:
            return
        expr = (expression or _default_expression()).strip()
        tag = (tts_emotion_tag or "").strip()

        if self._tts_pending_text and tag != self._tts_pending_emotion:
            self._flush_tts_pending()

        if not self._tts_pending_text:
            self._tts_pending_emotion = tag
            self._tts_pending_expr = expr
            self._tts_pending_action = action

        self._tts_pending_text += piece
        self._tts_pending_expr = expr
        if action:
            self._tts_pending_action = action

        pending_len = len(self._tts_pending_text)
        ends_sentence = piece[-1] in "。！？!?\n" if piece else False

        # 每句结束立即入队，避免仅首句合成、后续句滞留在 pending
        if ends_sentence or pending_len >= TTS_COALESCE_MAX_CHARS:
            self._flush_tts_pending()

    def _clear_translate_worker_ref(self, worker: _TranslateWorker) -> None:
        """QThread.deleteLater 后 C++ 对象会销毁，须同步清空 Python 引用。"""
        if self._translate_worker is worker:
            self._translate_worker = None

    def _emit_bubble_if_current(
        self,
        body: str,
        turn: int,
        *,
        bubble_seq: int,
        play_id: int | None = None,
        is_stream: bool = False,
    ) -> bool:
        """仅在轮次/分句序号仍有效时刷新气泡。"""
        if not (body or "").strip():
            return False
        if turn != self._turn_id:
            return False
        if play_id is not None and play_id != self._playback_play_id:
            return False
        if bubble_seq != self._bubble_translate_seq:
            return False
        if (
            self._tts_active_for_chat()
            and play_id is not None
            and not self._playback_active
        ):
            return False
        self._clear_bubble_thinking()
        self._display_answer_text = body
        self.bubble_changed.emit(body, is_stream)
        return True

    def _schedule_display_translate(
        self,
        text: str,
        turn: int,
        *,
        bubble_seq: int | None = None,
        play_id: int | None = None,
        is_stream: bool = False,
        force_display: bool = False,
    ) -> None:
        from pnn.pet.reply_text import bubble_text_for_reply

        text = bubble_text_for_reply(text)
        if not text:
            return
        # 语音模式播放前不刷整段，避免全文闪现；force_display 用于 TTS 失败等回退
        if (
            not force_display
            and self._tts_active_for_chat()
            and bubble_seq is None
            and play_id is None
        ):
            return
        if bubble_seq is None:
            self._bubble_translate_seq += 1
            seq = self._bubble_translate_seq
        else:
            seq = bubble_seq

        if not self._translate_enabled():
            self._emit_bubble_if_current(
                text,
                turn,
                bubble_seq=seq,
                play_id=play_id,
                is_stream=is_stream,
            )
            return

        from pnn.translate.service import translate_service

        cached = translate_service.peek_bubble_translation(text)
        if cached is not None:
            self._emit_bubble_if_current(
                cached,
                turn,
                bubble_seq=seq,
                play_id=play_id,
                is_stream=is_stream,
            )
            return

        # 需要翻译：禁止先展示原文，保持「…」直至译文就绪

        worker = _TranslateWorker(text, parent=self)
        self._translate_worker = worker

        def _apply(translated: str) -> None:
            self._emit_bubble_if_current(
                translated,
                turn,
                bubble_seq=seq,
                play_id=play_id,
                is_stream=is_stream,
            )

        def _fallback() -> None:
            self._emit_bubble_if_current(
                text,
                turn,
                bubble_seq=seq,
                play_id=play_id,
                is_stream=is_stream,
            )

        worker.finished_ok.connect(_apply)
        worker.failed.connect(_fallback)
        worker.finished.connect(lambda: self._clear_translate_worker_ref(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _enqueue_seg(
        self,
        text: str,
        expression: str,
        action: str | None = None,
        tts_emotion_tag: str | None = None,
    ) -> None:
        piece = text.strip()
        if not piece:
            return
        if self._seg_piece_redundant(piece):
            return
        self._fix_erroneous_merged_segs(piece)
        if piece in self._seg_seen:
            return
        if len(self._seg_texts) >= MAX_TTS_SEGMENTS:
            logger.warning("TTS 分句已达上限 %s，跳过后续", MAX_TTS_SEGMENTS)
            return
        self._seg_seen.add(piece)
        idx = len(self._seg_texts)
        if action:
            from pnn.pet.actions import resolve_action_name

            resolved = resolve_action_name(action)
            if resolved:
                self._seg_actions[idx] = resolved
        self._seg_texts.append(piece)
        from pnn.pet.bilingual_reply import chinese_display_for_segment

        self._seg_display_zh.append(
            chinese_display_for_segment(
                self._raw_answer_text,
                piece,
                seg_index=idx,
            )
        )
        self._seg_exprs.append(expression)
        self._seg_tts_tags.append((tts_emotion_tag or "").strip())
        preview = piece.replace("\n", " ")[:40]
        if pet_console_verbose():
            log_tts("分句", f"登记 #{idx + 1}（{len(piece)} 字）{preview}")
        self._sync_pipeline_status()
        self._pump_seg_synth()

    def _resolve_seg_emotion_tag(self, index: int) -> str | None:
        raw = ""
        if index < len(self._seg_tts_tags):
            raw = (self._seg_tts_tags[index] or "").strip()
        text = self._seg_texts[index] if index < len(self._seg_texts) else ""
        try:
            from pnn.characters.service import character_pack_service

            character_pack_service.ensure_migrated()
            cid = character_pack_service.get_active_id()
            return resolve_segment_emotion_tag(raw, text, cid)
        except Exception:
            return raw or None

    def _pump_seg_synth(self) -> None:
        """按播放顺序串行合成，避免 GPT-SoVITS 并发请求卡死。"""
        if len(self._seg_synth) >= MAX_TTS_SYNTH_PARALLEL:
            return
        for idx in range(self._seg_play_idx, len(self._seg_texts)):
            if idx in self._seg_audio or idx in self._seg_synth or idx in self._seg_failed:
                continue
            self._start_seg_synth(idx, self._seg_texts[idx])
            if len(self._seg_synth) >= MAX_TTS_SYNTH_PARALLEL:
                break

    def _start_seg_synth(self, index: int, text: str) -> None:
        turn = self._turn_id
        self._seg_synth.add(index)
        self._show_tts_synth(text, 5)
        emotion_tag = self._resolve_seg_emotion_tag(index)
        bar_label = f"句{index + 1}"
        if emotion_tag:
            bar_label = f"{bar_label} [{emotion_tag}]"
        seg_preview = text.replace("\n", " ")[:32]
        worker = _TtsWorker(
            self._api,
            text,
            emotion_tag=emotion_tag,
            progress_label=f"{bar_label} {seg_preview}",
            cancel=self._stream_cancel,
            retries=2,
            display_text=self._display_for_voice_log(text, index),
            parent=self,
        )
        worker.progress_changed.connect(self._on_tts_worker_progress)
        worker.finished_ok.connect(lambda wav: self._on_seg_synth_done(index, wav, turn))
        worker.failed.connect(lambda err: self._on_seg_synth_failed(index, err, turn))
        _start_thread(worker)

    def _on_seg_synth_done(self, index: int, payload: object, turn: int) -> None:
        if self._is_stale_turn(turn):
            self._seg_synth.discard(index)
            return
        self._seg_synth.discard(index)
        from pnn.pet.audio import wav_playback_info

        raw_chunks: list[tuple[str, bytes]] = list(payload)  # type: ignore[arg-type]
        if not raw_chunks:
            self._on_seg_synth_failed(index, "TTS 返回空音频", turn)
            return
        valid: list[tuple[str, bytes]] = []
        for sub_text, wav in raw_chunks:
            ok, reason, _dur = wav_playback_info(wav)
            if not ok:
                log_tts("失败", f"分句[{index}] 子段无效: {reason}")
                continue
            valid.append((sub_text, wav))
        if not valid:
            self._on_seg_synth_failed(index, "TTS 返回空音频", turn)
            return
        if len(valid) == 1:
            self._seg_chunk_remain.pop(index, None)
            self._seg_audio[index] = valid[0][1]
        else:
            self._seg_chunk_remain[index] = valid
            self._seg_audio[index] = valid[0][1]
            log_tts("合成", f"分句[{index + 1}] 共 {len(valid)} 段音频，按子句播报")
        self._sync_pipeline_status()
        self._pump_seg_play()
        self._pump_seg_synth()

    def _on_seg_synth_failed(self, index: int, err: str, turn: int) -> None:
        if self._is_stale_turn(turn):
            self._seg_synth.discard(index)
            return
        self._clear_tts_synth_ui()
        self._seg_synth.discard(index)
        self._seg_failed.add(index)
        self._seg_audio.pop(index, None)
        self._seg_chunk_remain.pop(index, None)
        log_tts("失败", f"分句[{index + 1}]: {err}")
        self._pump_seg_synth()
        if not self._playback_active and not self._play_queue:
            self._pump_seg_play()
        if not self._pipeline_active():
            self._emit_status(f"TTS: {err}", True)
            self._show_bubble_fallback(turn)
            self.playback_finished.emit()

    def _pump_seg_play(self) -> None:
        if self._playback_active or self._play_queue:
            return
        while self._seg_play_idx < len(self._seg_texts):
            idx = self._seg_play_idx
            wav = self._seg_audio.get(idx)
            if wav is None:
                if idx in self._seg_synth:
                    return
                if idx in self._seg_failed:
                    log_tts("播放", f"跳过分句[{idx + 1}]（合成失败）")
                    self._seg_play_idx += 1
                    continue
                self._pump_seg_synth()
                return
            chunks = self._seg_chunk_remain.get(idx)
            raw = self._seg_texts[idx]
            if chunks:
                text, wav = chunks[0]
            else:
                from pnn.pet.reply_text import bubble_text_for_reply

                text = bubble_text_for_reply(raw) or raw
            tts_tag = self._resolve_seg_emotion_tag(idx)
            llm_expr = (
                self._seg_exprs[idx]
                if idx < len(self._seg_exprs)
                else _default_expression()
            )
            expr = pick_expression_for_segment(
                raw,
                tts_tag=tts_tag,
                llm_expr=llm_expr,
                available=self._expr_available or set(),
            )
            from pnn.pet.audio import wav_playback_info

            _ok, _reason, dur = wav_playback_info(wav)
            audio_ms = int(max(0.0, dur if _ok else 0.0) * 1000)
            min_total = max(3500, audio_ms + 1500) if audio_ms else 5000
            if not self._live2d.play_expression_performance(
                expr, hold_ms=2000, min_total_ms=min_total
            ):
                self._live2d.set_expression(expr)
            action_name = self._seg_actions.pop(idx, None)
            action_name = pick_action_for_segment(
                raw,
                tts_tag=tts_tag,
                llm_action=action_name,
                llm_expr=expr,
            )
            if action_name:
                from pnn.pet.actions import speech_action_min_duration_ms

                min_ms = speech_action_min_duration_ms(dur if _ok else 0.0)
                if pet_console_verbose():
                    print(
                        f"[pet-ai] 句动作: {action_name}"
                        + (f" (情绪:{tts_tag})" if tts_tag else ""),
                        flush=True,
                    )
                self._live2d.perform_action(action_name, min_duration_ms=min_ms)
            if pet_console_verbose():
                tag_note = f" 情绪:{tts_tag}" if tts_tag else ""
                print(f"[pet-ai] 句表情: {expr}{tag_note}", flush=True)
            turn = self._turn_id

            def _on_end(*, seg_idx: int = idx) -> None:
                rest = self._seg_chunk_remain.get(seg_idx)
                if rest and len(rest) > 1:
                    self._seg_chunk_remain[seg_idx] = rest[1:]
                    sub_t, sub_w = rest[1]
                    self._play_audio(
                        sub_t,
                        sub_w,
                        on_end=_on_end,
                        bubble_turn=turn,
                    )
                    return
                self._seg_chunk_remain.pop(seg_idx, None)
                self._on_seg_play_ended()

            self._play_audio(text, wav, on_end=_on_end, bubble_turn=turn)
            return
        if self._tts_pending_text.strip():
            self._flush_tts_pending()
            self._pump_seg_synth()
            return
        if not self._seg_synth and self._seg_play_idx >= len(self._seg_texts):
            self._finish_all_playback()

    def _on_seg_play_ended(self) -> None:
        self._seg_audio.pop(self._seg_play_idx, None)
        self._seg_play_idx += 1
        self._pump_seg_synth()
        self._pump_seg_play()

    def _show_tts_synth(self, text: str, percent: int) -> None:
        del text, percent
        # 合成阶段不刷新气泡，避免与播放中的句子叠成两个框

    def _on_tts_worker_progress(self, message: str, percent: int) -> None:
        self.tts_synth_progress.emit(message, percent)
        if pet_console_verbose() and percent >= 0 and (message or "").strip():
            log_tts("进度", f"{message} ({percent}%)")

    def _clear_tts_synth_ui(self) -> None:
        self.tts_synth_progress.emit("", -1)

    def _play_audio(
        self,
        bubble_text: str,
        wav: bytes,
        *,
        on_end,
        bubble_turn: int | None = None,
        bubble_literal: bool = False,
    ) -> None:
        turn = self._turn_id if bubble_turn is None else bubble_turn
        self._play_queue.append(
            _PlayItem(
                bubble_text,
                wav,
                on_end,
                bubble_turn=turn,
                play_id=0,
                bubble_literal=bubble_literal,
            ),
        )
        self._pump_play_queue()

    def _pump_play_queue(self) -> None:
        if self._playback_active or not self._play_queue:
            return
        item = self._play_queue.pop(0)
        from pnn.pet.audio import wav_playback_info

        ok, reason, _dur = wav_playback_info(item.wav)
        if not ok:
            log_tts("播放", f"跳过无效音频: {reason}")
            if item.on_end is not None:
                item.on_end()
            self._pump_play_queue()
            return

        self._clear_tts_synth_ui()
        bubble = (item.bubble_text or "").strip()
        skip_hint_bubble = (
            self._screenshot_flow_active
            and bubble == self._screenshot_hint_display
            and (self._screenshot_analysis_tts_text or "").strip()
        )
        self._playback_seq += 1
        seq = self._playback_seq
        self._playback_play_id += 1
        item.play_id = self._playback_play_id
        play_id = item.play_id
        self._last_mouth = -1.0
        try:
            self._lip.start(item.wav)
        except Exception as exc:
            log_tts("播放", f"启动失败: {exc}")
            if item.on_end is not None:
                item.on_end()
            self._pump_play_queue()
            return
        self._playback_active = True
        self._live2d.set_playing_speech(True)
        self.playback_started.emit()
        if bubble and not skip_hint_bubble and self._voice_output_enabled:
            self._bubble_translate_seq += 1
            literal = item.bubble_literal
            if literal:
                self._playback_bubble_pending = None
                self._playback_bubble_wait_ticks = 0
                self._emit_playback_bubble(
                    bubble,
                    item.bubble_turn,
                    play_id=play_id,
                    literal=True,
                )
            else:
                self._playback_bubble_pending = (bubble, item.bubble_turn, play_id, False)
                self._playback_bubble_wait_ticks = 0
                # 不在此处刷「…」：首句由 loading 阶段已显示；分句切换保留上一句直至新句就绪
            if self._screenshot_flow_active:
                from pnn.pet.reply_text import bubble_text_for_reply

                preview = bubble_text_for_reply(bubble).replace("\n", " ")[:120]
                if preview:
                    print(f"[pet-ai] 截图播报: {preview}", flush=True)
        self._mouth_timer.start()
        self._sync_pipeline_status()

        def _ended() -> None:
            if item.on_end is not None:
                item.on_end()
            self._pump_play_queue()

        self._playback_poll_seq = seq
        self._playback_poll_on_end = _ended
        self._playback_poll.start()

    def _tick_playback_poll(self) -> None:
        seq = self._playback_poll_seq
        if seq != self._playback_seq:
            self._playback_poll.stop()
            self._playback_poll_on_end = None
            return
        if self._lip.playback_active():
            return
        self._playback_poll.stop()
        self._mouth_timer.stop()
        self._last_mouth = 0.0
        self._live2d.set_mouth_open(0.0)
        self._clear_playback_bubble_pending()
        self._playback_active = False
        self._live2d.set_playing_speech(False)
        on_end = self._playback_poll_on_end
        self._playback_poll_on_end = None
        if on_end is not None and seq == self._playback_seq:
            on_end()

    def _finish_all_playback(self) -> None:
        self._play_queue.clear()
        self._reset_tts_state()
        self._disarm_stall_guard()
        self._sync_pipeline_status()
        if pet_console_verbose():
            log_tts("播放", "全部语音播放结束")
        self._live2d.release_expression_performance()
        self._flush_pending_memory()
        # 气泡由 app._on_playback_finished 按阅读时长延迟关闭，勿在此立即清空
        self.playback_finished.emit()

    def stop_audio(self, *, emit_finished: bool = False) -> None:
        was_active = self._playback_active
        self._invalidate_bubble_translates()
        self._clear_playback_bubble_pending()
        self._clear_tts_synth_ui()
        self._playback_seq += 1
        self._playback_poll.stop()
        self._playback_poll_on_end = None
        self._play_queue.clear()
        self._reset_tts_state()
        self._playback_active = False
        self._lip.stop()
        self._mouth_timer.stop()
        self._live2d.set_mouth_open(0.0)
        self._live2d.set_playing_speech(False)
        self._live2d.release_expression_performance()
        if emit_finished and was_active:
            self.playback_finished.emit()
