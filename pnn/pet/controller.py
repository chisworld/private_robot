"""桌宠对话编排：LLM 流式 → 表情 → TTS 口型。"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QElapsedTimer, Qt, QThread, QTimer, Signal

from pnn.pet.api_client import ChatMessage, PetApiClient
from pnn.pet.audio import LipSyncPlayer
from pnn.pet.console_log import log_ai_reply, log_tts
from pnn.pet.action_catalog import build_llm_action_instruction
from pnn.pet.expression_catalog import build_llm_expression_instruction, discover_expression_names
from pnn.pet.expression_tags import (
    parse_tagged_piece,
    pull_final_tagged_chunk,
    pull_tagged_tts_chunks,
    strip_expression_tags,
)

if TYPE_CHECKING:
    from pnn.pet.live2d_widget import Live2DWidget

logger = logging.getLogger(__name__)


def _default_expression() -> str:
    from pnn.pet.paths import DEFAULT_EXPRESSION

    return DEFAULT_EXPRESSION

# 分句模式下同时向 TTS 提交的合成任务数（过大易占满 CPU/GPU 导致界面卡顿）
MAX_TTS_SYNTH_PARALLEL = 2
# 单轮对话最多排队分句数，防止流式重复切分撑爆线程与内存
MAX_TTS_SEGMENTS = 12
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

    def run(self) -> None:
        preview = self._message.replace("\n", " ")[:120]
        if self._image_base64:
            preview = f"[附图] {preview}".strip()
        print(f"[pet-llm] 用户: {preview}", flush=True)

        def on_delta(full: str) -> None:
            if self._cancel is not None and self._cancel.is_set():
                return
            self.delta_changed.emit(full)

        result = self._api.stream_chat(
            self._message,
            self._history,
            on_delta=on_delta if self._stream_deltas else None,
            on_agent_status=lambda s: self.agent_status.emit(s),
            pet_expression_prompt=self._pet_expression_prompt,
            image_base64=self._image_base64,
            image_mime=self._image_mime,
            image_analysis=self._image_analysis,
            cancel=self._cancel,
        )
        if self._cancel is not None and self._cancel.is_set():
            return
        if result.error:
            self.failed.emit(result.error)
        elif result.text:
            self.finished_ok.emit(result.text)
        else:
            self.failed.emit("模型未返回内容")


class _TranslateWorker(QThread):
    """后台翻译，避免百度 API 阻塞 UI 线程。"""

    finished_ok = Signal(str)

    def __init__(self, text: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._text = text

    def run(self) -> None:
        try:
            from pnn.translate.service import translate_service

            if translate_service.display_translation_for_bubble():
                out = translate_service.to_display_chinese(self._text)
            else:
                out = self._text
        except Exception:
            out = self._text
        self.finished_ok.emit(out)


@dataclass
class _PlayItem:
    bubble_text: str
    wav: bytes
    on_end: Callable[[], None] | None = None


class _TtsWorker(QThread):
    finished_ok = Signal(bytes)
    failed = Signal(str)
    progress_changed = Signal(str, int)

    def __init__(
        self,
        api: PetApiClient,
        text: str,
        *,
        cancel: threading.Event | None = None,
        retries: int = 0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._text = text
        self._cancel = cancel
        self._retries = max(0, retries)

    def run(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            return
        preview = self._text.replace("\n", " ")[:40]
        log_tts("合成", f"开始 {preview}")
        try:
            from pnn.pet.audio import concat_wav_bytes
            from pnn.tts.text_sanitize import split_for_tts

            segments = split_for_tts(self._text)
            if not segments:
                self.failed.emit("TTS 文本为空")
                return
            parts: list[bytes] = []
            for seg in segments:
                if self._cancel is not None and self._cancel.is_set():
                    return
                data = self._synthesize_with_retry(seg)
                if self._cancel is not None and self._cancel.is_set():
                    return
                if not data or len(data) < 44:
                    self.failed.emit("TTS 返回空音频")
                    return
                parts.append(data)
            data = concat_wav_bytes(parts)
            if not data or len(data) < 44:
                self.failed.emit("TTS 返回空音频")
                return
            log_tts("合成", f"完成 {len(data)} 字节")
            self.finished_ok.emit(data)
        except InterruptedError:
            return
        except Exception as exc:
            if self._cancel is not None and self._cancel.is_set():
                return
            log_tts("失败", str(exc))
            self.failed.emit(str(exc))

    def _synthesize_with_retry(self, text: str) -> bytes:
        import time

        last_err = "TTS 返回空音频"
        for attempt in range(self._retries + 1):
            if self._cancel is not None and self._cancel.is_set():
                raise InterruptedError("TTS 已取消")
            try:
                data = self._api.synthesize_tts(
                    text,
                    log_progress=False,
                    cancel=self._cancel,
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
            # 识图耗时较长，并行预热 TTS，避免摘要合成时模型尚未就绪
            self._api.ensure_tts_ready(timeout=90.0)
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
            out.append((display, wav))
        log_tts("合成", f"摘要共 {len(out)} 句")
        self.finished_ok.emit(out)


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
        self._stream_bubble_output = False
        self._tts_spoken_offset = 0
        self._playback_active = False
        self._turn_id = 0

        # 分句朗读：并行合成 + 按序播放
        self._seg_texts: list[str] = []
        self._seg_exprs: list[str] = []
        self._seg_audio: dict[int, bytes] = {}
        self._seg_actions: dict[int, str] = {}
        self._seg_synth: set[int] = set()
        self._seg_seen: set[str] = set()

        self._seg_play_idx = 0
        self._expr_names: list[str] | None = None
        self._expr_available: set[str] = set()
        self._pet_expr_prompt: str | None = None
        self._stream_last_expr: str | None = None
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

        self._mouth_timer = QTimer(self)
        self._mouth_timer.setInterval(16)
        self._mouth_timer.timeout.connect(self._poll_mouth)

        self._playback_poll = QTimer(self)
        self._playback_poll.setInterval(80)
        self._playback_poll.timeout.connect(self._tick_playback_poll)
        self._playback_poll_on_end = None

    def set_voice_output_enabled(self, enabled: bool) -> None:
        self._voice_output_enabled = bool(enabled)
        if not self._voice_output_enabled:
            self.stop_audio(emit_finished=True)

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
        """开启语音时：LLM/合成/等待播放阶段显示 …，仅播放中改由分句气泡展示正文。"""
        if not self._voice_output_enabled or self._playback_active:
            return
        waiting = self._loading or bool(self._seg_synth)
        if not waiting and self._seg_texts:
            idx = self._seg_play_idx
            if idx < len(self._seg_texts) and idx not in self._seg_audio:
                waiting = True
        if waiting:
            self.bubble_changed.emit("…", False)

    def _emit_status(self, msg: str, is_err: bool = False) -> None:
        if msg == self._last_status and is_err == self._last_status_err:
            return
        self._last_status = msg
        self._last_status_err = is_err
        self.status_changed.emit(msg, is_err)

    def _poll_mouth(self) -> None:
        v = self._lip.mouth_open_y()
        if abs(v - self._last_mouth) < 0.02:
            return
        self._last_mouth = v
        self._live2d.set_mouth_open(v)

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

    def prepare(self) -> bool:
        if not self._api.health():
            self._emit_status("API 未启动 (8765)", True)
            return False
        return True

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

        lang = active_reply_language()
        display, _tts = get_screenshot_hint(lang)
        img = (image_base64 or "").strip()
        self._pending_screenshot_analysis = ""
        self._screenshot_flow_active = True
        self._screenshot_hint_played = False
        self._screenshot_analysis_played = False
        self._screenshot_analysis_tts_text = ""
        self._screenshot_vision_pending = bool(img and vision_configured())
        self._screenshot_hint_display = display
        self._screenshot_vision_error = ""

        self.bubble_changed.emit("", False)
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
        self._screenshot_analysis_played = True
        items: list[tuple[str, bytes]] = list(segments)  # type: ignore[arg-type]
        if not items:
            self._maybe_finish_screenshot_flow()
            return
        for i, (display, wav) in enumerate(items):
            is_last = i == len(items) - 1

            def _on_end(*, last: bool = is_last) -> None:
                if last:
                    self._maybe_finish_screenshot_flow()

            self._play_audio(display, wav, on_end=_on_end)

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

        self._play_audio(bubble_text, wav, on_end=on_end)

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
        if pending_analysis and not self._screenshot_analysis_played:
            worker = self._screenshot_analysis_tts_worker
            if _qthread_running(worker):
                return
            self._try_start_analysis_tts()
            return
        self._screenshot_flow_active = False
        self.playback_finished.emit()

    def _ensure_expression_catalog(self) -> None:
        if self._expr_names is not None:
            return
        self._expr_names = discover_expression_names()
        self._expr_available = set(self._expr_names)
        expr_prompt = build_llm_expression_instruction(self._expr_names)
        action_prompt = build_llm_action_instruction()
        self._pet_expr_prompt = expr_prompt + "\n\n" + action_prompt

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
        self._seg_exprs.clear()
        self._seg_audio.clear()
        self._seg_actions.clear()
        self._seg_synth.clear()
        self._seg_seen.clear()
        self._seg_play_idx = 0
        self._tts_spoken_offset = 0
        self._stream_last_expr = None
        self._raw_answer_text = ""

    def interrupt_current(self) -> None:
        self._turn_id += 1
        self._stream_cancel.set()
        was_loading = self._loading
        self.stop_audio()
        self._reset_tts_state()
        if was_loading and self._history and self._history[-1].role == "user":
            self._history.pop()
        if was_loading:
            self._loading = False
            self.loading_changed.emit(False)
            self.bubble_changed.emit("", False)

    def send_message(
        self,
        text: str,
        *,
        interrupt: bool = False,
        image_base64: str = "",
        image_mime: str = "image/png",
        image_analysis: str = "",
    ) -> None:
        msg = text.strip()
        img = (image_base64 or "").strip()
        if not msg and not img:
            return
        if self.is_busy():
            if not interrupt:
                return
            self.interrupt_current()
        turn = self._turn_id
        self._stream_cancel.clear()
        self._loading = True
        self._answer_text = ""
        self._display_answer_text = ""
        self._raw_answer_text = ""
        self._reset_tts_state()
        self.loading_changed.emit(True)
        if self._voice_output_enabled:
            self.bubble_changed.emit("…", False)
        else:
            self.bubble_changed.emit("", False)
        self._last_delta_len = 0
        self._last_bubble_emit_snapshot = ""
        self._delta_throttle.restart()
        self._emit_status("思考中…", False)

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
        self._ensure_expression_catalog()

        worker = _ChatWorker(
            self._api,
            msg,
            self._history[:-1],
            stream_deltas=True,
            pet_expression_prompt=self._pet_expr_prompt,
            image_base64=img,
            image_mime=image_mime or "image/png",
            image_analysis=(image_analysis or self._pending_screenshot_analysis or "").strip(),
            cancel=self._stream_cancel,
            parent=self,
        )
        self._pending_screenshot_analysis = ""
        self._chat_worker = worker
        worker.failed.connect(lambda err: self._on_chat_failed(err, turn))
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

    def _on_chat_delta(self, full: str, turn: int) -> None:
        if turn != self._turn_id:
            return
        self._raw_answer_text = full
        self._answer_text = strip_expression_tags(full)
        self._display_answer_text = self._answer_text
        chunks, self._tts_spoken_offset, self._stream_last_expr = pull_tagged_tts_chunks(
            full,
            self._tts_spoken_offset,
            available=self._expr_available,
            last_expr=self._stream_last_expr,
        )
        for expr, piece, action in chunks:
            self._enqueue_tts(piece, expr, action)
        if self._stream_bubble_output and self._answer_text:
            elapsed = self._delta_throttle.elapsed()
            if elapsed > 200 and self._answer_text != self._last_bubble_emit_snapshot:
                self._last_bubble_emit_snapshot = self._answer_text
                self._delta_throttle.restart()
                self._schedule_display_translate(
                    self._answer_text, turn, bubble_seq=None, is_stream=True
                )

    def _on_chat_failed(self, err: str, turn: int) -> None:
        if turn != self._turn_id:
            return
        self._loading = False
        self.loading_changed.emit(False)
        self.bubble_changed.emit("", False)
        self._history.pop()
        self._emit_status(f"对话: {err}", True)
        print(f"[pet-llm] 失败: {err}", flush=True)

    def _on_chat_done(self, full: str, turn: int) -> None:
        if self._is_stale_turn(turn):
            return
        self._loading = False
        self.loading_changed.emit(False)
        self._raw_answer_text = full
        clean = strip_expression_tags(full)
        self._answer_text = clean
        self._display_answer_text = clean
        self._history.append(ChatMessage(role="assistant", content=clean))
        self._trim_history()
        log_ai_reply(clean, expression=self._stream_last_expr or _default_expression())
        self._notify_memory_turn(self._last_user_msg, clean)

        if not clean:
            self.bubble_changed.emit("", False)

        if not self._voice_output_enabled:
            if self._stream_bubble_output and clean:
                self._schedule_display_translate(clean, turn, is_stream=False)
            self._sync_pipeline_status()
            self.playback_finished.emit()
            return

        has_tts = bool(clean.strip())
        if has_tts:
            tail_pack, self._tts_spoken_offset, self._stream_last_expr = (
                pull_final_tagged_chunk(
                    full,
                    self._tts_spoken_offset,
                    available=self._expr_available,
                    last_expr=self._stream_last_expr,
                )
            )
            if tail_pack:
                expr, piece, action = tail_pack
                if not (self._seg_texts and self._seg_texts[-1] == piece):
                    self._enqueue_tts(piece, expr, action)
            self._pump_seg_synth()
            self._pump_seg_play()
        if not self._pipeline_active():
            self._sync_pipeline_status()
            if not has_tts:
                self.playback_finished.emit()

    def _notify_memory_turn(self, user_message: str, assistant_reply: str) -> None:
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
                memory_service.after_conversation_turn(
                    user_message, assistant_reply, history
                )
            except Exception as exc:
                logger.warning("记忆写入失败: %s", exc)
            finally:
                self._memory_turn_lock.release()

        threading.Thread(target=_run, daemon=True, name="pet-memory-turn").start()

    def _translate_enabled(self) -> bool:
        try:
            from pnn.translate.service import translate_service

            return translate_service.display_translation_for_bubble()
        except Exception:
            return False

    def _show_segment_bubble(self, text: str, turn: int) -> None:
        """仅在实际播放该句语音时更新气泡（需已开启语音输出）。"""
        if not self._voice_output_enabled:
            return
        piece = (text or "").strip()
        if not piece or self._is_stale_turn(turn):
            return
        self._stream_translate_seq += 1
        self._stream_translate_worker = None
        self._bubble_translate_seq += 1
        seq = self._bubble_translate_seq
        self._schedule_display_translate(piece, turn, bubble_seq=seq)

    def _enqueue_tts(self, text: str, expression: str | None = None, action: str | None = None) -> None:
        if not self._voice_output_enabled:
            return
        piece = text.strip()
        if not piece:
            return
        expr = (expression or _default_expression()).strip()
        self._enqueue_seg(piece, expr, action)

    def _clear_translate_worker_ref(self, worker: _TranslateWorker) -> None:
        """QThread.deleteLater 后 C++ 对象会销毁，须同步清空 Python 引用。"""
        if self._translate_worker is worker:
            self._translate_worker = None

    def _schedule_display_translate(
        self,
        text: str,
        turn: int,
        *,
        bubble_seq: int | None = None,
        is_stream: bool = False,
    ) -> None:
        # 流式输出时跳过翻译，避免并发请求拖慢显示
        if is_stream or not self._translate_enabled():
            self.bubble_changed.emit(text, is_stream)
            return

        worker = _TranslateWorker(text, parent=self)
        self._translate_worker = worker

        def _apply(translated: str) -> None:
            if turn != self._turn_id:
                return
            if bubble_seq is not None and bubble_seq != self._bubble_translate_seq:
                return
            self._display_answer_text = translated
            self.bubble_changed.emit(translated, is_stream)

        worker.finished_ok.connect(_apply)
        worker.finished.connect(lambda: self._clear_translate_worker_ref(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _enqueue_seg(self, text: str, expression: str, action: str | None = None) -> None:
        piece = text.strip()
        if not piece:
            return
        if piece in self._seg_seen:
            return
        if len(self._seg_texts) >= MAX_TTS_SEGMENTS:
            logger.warning("TTS 分句已达上限 %s，跳过后续", MAX_TTS_SEGMENTS)
            return
        self._seg_seen.add(piece)
        idx = len(self._seg_texts)
        if action:
            self._seg_actions[idx] = action
        self._seg_texts.append(piece)
        self._seg_exprs.append(expression)
        self._sync_pipeline_status()
        self._pump_seg_synth()

    def _pump_seg_synth(self) -> None:
        """并行启动多段合成（最多 MAX_TTS_SYNTH_PARALLEL 路）。"""
        for idx, seg in enumerate(self._seg_texts):
            if idx in self._seg_audio or idx in self._seg_synth:
                continue
            if len(self._seg_synth) >= MAX_TTS_SYNTH_PARALLEL:
                break
            self._start_seg_synth(idx, seg)

    def _start_seg_synth(self, index: int, text: str) -> None:
        turn = self._turn_id
        self._seg_synth.add(index)
        self._show_tts_synth(text, 5)
        worker = _TtsWorker(self._api, text, cancel=self._stream_cancel, parent=self)
        worker.progress_changed.connect(self._on_tts_worker_progress)
        worker.finished_ok.connect(lambda wav: self._on_seg_synth_done(index, wav, turn))
        worker.failed.connect(lambda err: self._on_seg_synth_failed(index, err, turn))
        _start_thread(worker)

    def _on_seg_synth_done(self, index: int, wav: bytes, turn: int) -> None:
        if self._is_stale_turn(turn):
            self._seg_synth.discard(index)
            return
        self._seg_synth.discard(index)
        self._seg_audio[index] = wav
        self._sync_pipeline_status()
        self._pump_seg_synth()
        self._pump_seg_play()

    def _on_seg_synth_failed(self, index: int, err: str, turn: int) -> None:
        if self._is_stale_turn(turn):
            self._seg_synth.discard(index)
            return
        self._clear_tts_synth_ui()
        self._seg_synth.discard(index)
        self._seg_audio.pop(index, None)
        log_tts("失败", f"分句[{index}]: {err}")
        self._pump_seg_synth()
        if index == self._seg_play_idx and not self._playback_active:
            self._seg_play_idx += 1
            self._pump_seg_play()
        if not self._pipeline_active():
            self._emit_status(f"TTS: {err}", True)
            self.playback_finished.emit()

    def _pump_seg_play(self) -> None:
        if self._playback_active or self._play_queue:
            return
        while self._seg_play_idx < len(self._seg_texts):
            idx = self._seg_play_idx
            wav = self._seg_audio.get(idx)
            if wav is None:
                return
            text = self._seg_texts[idx]
            expr = (
                self._seg_exprs[idx]
                if idx < len(self._seg_exprs)
                else _default_expression()
            )
            self._live2d.set_expression(expr)
            action_name = self._seg_actions.pop(idx, None)
            if action_name:
                print(f"[pet-ai] 句动作: {action_name}", flush=True)
                self._live2d.perform_action(action_name)
            print(f"[pet-ai] 句表情: {expr}", flush=True)
            turn = self._turn_id
            self._show_segment_bubble(text, turn)
            self._play_audio(text, wav, on_end=self._on_seg_play_ended)
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

    def _clear_tts_synth_ui(self) -> None:
        self.tts_synth_progress.emit("", -1)

    def _play_audio(self, bubble_text: str, wav: bytes, *, on_end) -> None:
        self._play_queue.append(_PlayItem(bubble_text, wav, on_end))
        self._pump_play_queue()

    def _pump_play_queue(self) -> None:
        if self._playback_active or not self._play_queue:
            return
        item = self._play_queue.pop(0)
        if not item.wav or len(item.wav) < 44:
            log_tts("播放", "跳过无效音频")
            if item.on_end is not None:
                item.on_end()
            self._pump_play_queue()
            return

        self._clear_tts_synth_ui()
        log_tts("播放", f"开始播放（{len(item.wav)} 字节，队列余 {len(self._play_queue)}）")
        bubble = (item.bubble_text or "").strip()
        if bubble:
            self.bubble_changed.emit(bubble, False)
        self._playback_seq += 1
        seq = self._playback_seq
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
        self._playback_active = False
        self._live2d.set_playing_speech(False)
        self._live2d.set_expression(_default_expression())
        on_end = self._playback_poll_on_end
        self._playback_poll_on_end = None
        if on_end is not None and seq == self._playback_seq:
            on_end()

    def _finish_all_playback(self) -> None:
        self._play_queue.clear()
        self._reset_tts_state()
        self._sync_pipeline_status()
        log_tts("播放", "全部语音播放结束")
        self._live2d.set_expression(_default_expression())
        self.bubble_changed.emit("", False)
        self.playback_finished.emit()

    def stop_audio(self, *, emit_finished: bool = False) -> None:
        was_active = self._playback_active
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
        self._live2d.set_expression(_default_expression())
        if emit_finished and was_active:
            self.playback_finished.emit()
