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

# 分句并行合成上限（9880 并发 HTTP；GPU 可能排队）
# GPT-SoVITS 在 API 侧已串行推理；桌宠侧限制并发，避免占满 HTTP 线程池
MAX_TTS_SYNTH_PARALLEL = 2
# 同情绪标签的连续句合并为一次 TTS（减少多次冷启动）；首句仍立即送出以尽快开读
TTS_COALESCE_MAX_CHARS = 200
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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._text = text
        self._emotion_tag = emotion_tag
        self._progress_label = (progress_label or "").strip()
        self._cancel = cancel
        self._retries = max(0, retries)

    def run(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            return
        preview = self._text.replace("\n", " ")[:40]
        try:
            from pnn.characters.reply_lang import active_reply_language
            from pnn.pet.reply_text import tts_text_for_reply
            from pnn.tts.text_sanitize import split_for_tts

            lang = active_reply_language()
            tts_source = tts_text_for_reply(self._text, lang)
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
        self._seg_tts_tags: list[str] = []
        self._seg_audio: dict[int, bytes] = {}
        self._seg_actions: dict[int, str] = {}
        self._seg_synth: set[int] = set()
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

        self._mouth_timer = QTimer(self)
        self._mouth_timer.setInterval(16)
        self._mouth_timer.timeout.connect(self._poll_mouth)

        self._playback_poll = QTimer(self)
        self._playback_poll.setInterval(80)
        self._playback_poll.timeout.connect(self._tick_playback_poll)
        self._playback_poll_on_end = None
        self._playback_bubble_pending: tuple[str, int, int, bool] | None = None
        self._playback_bubble_wait_ticks = 0

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

    def try_time_greeting(self) -> None:
        """每次启动按当前时段播放问候（优先本地 wav，无文件才后台合成）。"""
        if not self._voice_output_enabled or self.is_busy():
            return
        if _qthread_running(self._time_greeting_worker):
            return
        from pnn.characters.reply_lang import active_reply_language
        from pnn.pet.time_greeting import (
            get_time_greeting,
            load_time_greeting_wav,
            time_greeting_character_id,
        )

        lang = active_reply_language()
        cid = time_greeting_character_id()
        display, _tts, slot = get_time_greeting(lang, char_id=cid)
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
        self.bubble_changed.emit(display, False)

    def _play_time_greeting(self, display: str, wav: bytes) -> None:
        if not self._voice_output_enabled:
            return
        text = (display or "").strip()
        if text:
            self.bubble_changed.emit(text, False)
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
            emo = build_llm_emotion_tag_instruction(character_pack_service.get_active_id())
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
        self._seg_exprs.clear()
        self._seg_tts_tags.clear()
        self._seg_audio.clear()
        self._seg_actions.clear()
        self._seg_synth.clear()
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

    def _reconcile_tts_from_full(self, full: str) -> None:
        """流式结束后补登记漏掉的分句（保证整段回复都会进入 TTS 队列）。"""
        offset = 0
        expr = self._stream_last_expr
        emo = self._stream_last_emotion_tag
        added = 0
        while offset < len(full):
            chunks, new_off, expr, emo = pull_tagged_tts_chunks(
                full,
                offset,
                available=self._expr_available,
                last_expr=expr,
                last_emotion_tag=emo,
            )
            if not chunks and new_off <= offset:
                break
            for e, piece, action, tag in chunks:
                p = piece.strip()
                if p and p not in self._seg_seen:
                    self._enqueue_seg(p, e, action, tag)
                    added += 1
            offset = new_off
        tail_pack, _off, expr, emo = pull_final_tagged_chunk(
            full,
            offset,
            available=self._expr_available,
            last_expr=expr,
            last_emotion_tag=emo,
        )
        if tail_pack:
            e, piece, action, tag = tail_pack
            p = piece.strip()
            if p and p not in self._seg_seen:
                self._enqueue_seg(p, e, action, tag)
                added += 1
        if added:
            log_tts("批次", f"补登记 {added} 个分句")

    def _invalidate_bubble_translates(self) -> None:
        self._bubble_translate_seq += 1
        self._stream_translate_seq += 1
        self._playback_play_id += 1

    def interrupt_current(self) -> None:
        self._turn_id += 1
        self._stream_cancel.set()
        self._invalidate_bubble_translates()
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
        chunks, self._tts_spoken_offset, self._stream_last_expr, self._stream_last_emotion_tag = (
            pull_tagged_tts_chunks(
                full,
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
            and self._answer_text
            and not self._voice_output_enabled
        ):
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

        # 语音模式：作废流式阶段未完成的翻译，保持「…」直至首句播放
        self._bubble_translate_seq += 1
        self._stream_translate_seq += 1
        if clean.strip():
            self.bubble_changed.emit("…", False)

        has_tts = bool(clean.strip())
        if has_tts:
            self._flush_tts_pending()
            tail_pack, self._tts_spoken_offset, self._stream_last_expr, self._stream_last_emotion_tag = (
                pull_final_tagged_chunk(
                    full,
                    self._tts_spoken_offset,
                    available=self._expr_available,
                    last_expr=self._stream_last_expr,
                    last_emotion_tag=self._stream_last_emotion_tag,
                )
            )
            if tail_pack:
                expr, piece, action, tts_tag = tail_pack
                if not (self._seg_texts and self._seg_texts[-1] == piece):
                    self._enqueue_tts(piece, expr, action, tts_tag)
            self._flush_tts_pending()
            self._reconcile_tts_from_full(full)
            self._pump_seg_play()
            self._pump_seg_synth()
        if not self._pipeline_active():
            self._sync_pipeline_status()
            if (
                has_tts
                and clean.strip()
                and not self._seg_texts
                and not self._seg_audio
                and not self._seg_synth
            ):
                log_tts("失败", "语音合成未产出可播放音频，改为仅显示文字")
                if turn == self._turn_id:
                    self._schedule_display_translate(clean, turn, is_stream=False)
                self.playback_finished.emit()
            elif not has_tts:
                self.playback_finished.emit()
            # 仍有分句待播/待合成时：勿在此处 playback_finished，避免气泡提前“结束”卡住

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
        self.bubble_changed.emit(piece, False)
        if (
            literal
            or not self._translate_enabled()
            or self._screenshot_flow_active
        ):
            return
        self._bubble_translate_seq += 1
        seq = self._bubble_translate_seq
        self._schedule_display_translate(
            piece,
            turn,
            bubble_seq=seq,
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
        if not self._voice_output_enabled:
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

    def _schedule_display_translate(
        self,
        text: str,
        turn: int,
        *,
        bubble_seq: int | None = None,
        play_id: int | None = None,
        is_stream: bool = False,
    ) -> None:
        from pnn.pet.reply_text import bubble_text_for_reply

        text = bubble_text_for_reply(text)
        if not text:
            return
        # 流式输出时跳过翻译，避免并发请求拖慢显示
        if is_stream or not self._translate_enabled():
            if self._voice_output_enabled and bubble_seq is None:
                return
            self.bubble_changed.emit(text, is_stream)
            return

        worker = _TranslateWorker(text, parent=self)
        self._translate_worker = worker

        def _apply(translated: str) -> None:
            if turn != self._turn_id:
                return
            if play_id is not None and play_id != self._playback_play_id:
                return
            if bubble_seq is not None and bubble_seq != self._bubble_translate_seq:
                return
            # 语音模式仅接受带 bubble_seq 的分句翻译，忽略流式整段回调
            if self._voice_output_enabled and bubble_seq is None:
                return
            if (
                self._voice_output_enabled
                and play_id is not None
                and not self._playback_active
            ):
                return
            self._display_answer_text = translated
            self.bubble_changed.emit(translated, is_stream)

        worker.finished_ok.connect(_apply)
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
        self._seg_tts_tags.append((tts_emotion_tag or "").strip())
        self._sync_pipeline_status()
        self._pump_seg_synth()

    def _resolve_seg_emotion_tag(self, index: int) -> str | None:
        raw = ""
        if index < len(self._seg_tts_tags):
            raw = (self._seg_tts_tags[index] or "").strip()
        try:
            from pnn.characters.service import character_pack_service
            from pnn.tts.voice_library import load_voice_emotions, resolve_tts_emotion_tag

            character_pack_service.ensure_migrated()
            cid = character_pack_service.get_active_id()
            lib = load_voice_emotions(cid)
            default = (lib.default_emotion_id if lib else "") or "normal1"
            if raw:
                return resolve_tts_emotion_tag(raw, cid) or default
            return default if lib and lib.presets else None
        except Exception:
            return None

    def _pump_seg_synth(self) -> None:
        """并行启动多段合成；优先合成即将播放的下一句。"""
        slots = MAX_TTS_SYNTH_PARALLEL - len(self._seg_synth)
        if slots <= 0:
            return
        order: list[int] = []
        if self._seg_play_idx < len(self._seg_texts):
            order.append(self._seg_play_idx)
        for idx in range(len(self._seg_texts)):
            if idx not in order:
                order.append(idx)
        started = 0
        for idx in order:
            if started >= slots:
                break
            if idx in self._seg_audio or idx in self._seg_synth:
                continue
            self._start_seg_synth(idx, self._seg_texts[idx])
            started += 1

    def _start_seg_synth(self, index: int, text: str) -> None:
        turn = self._turn_id
        self._seg_synth.add(index)
        self._show_tts_synth(text, 5)
        emotion_tag = self._resolve_seg_emotion_tag(index)
        seg_preview = text.replace("\n", " ")[:32]
        bar_label = f"句{index + 1}"
        if emotion_tag:
            bar_label = f"{bar_label} [{emotion_tag}]"
        worker = _TtsWorker(
            self._api,
            text,
            emotion_tag=emotion_tag,
            progress_label=f"{bar_label} {seg_preview}",
            cancel=self._stream_cancel,
            retries=2,
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
        self._seg_audio.pop(index, None)
        self._seg_chunk_remain.pop(index, None)
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
            chunks = self._seg_chunk_remain.get(idx)
            if chunks:
                text, wav = chunks[0]
            else:
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
        if percent >= 0 and (message or "").strip():
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

        ok, reason, dur = wav_playback_info(item.wav)
        if not ok:
            log_tts("播放", f"跳过无效音频: {reason}")
            if item.on_end is not None:
                item.on_end()
            self._pump_play_queue()
            return

        self._clear_tts_synth_ui()
        log_tts(
            "播放",
            f"开始播放（{len(item.wav)} 字节，约 {dur:.1f}s，队列余 {len(self._play_queue)}）",
        )
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
                self.bubble_changed.emit("…", False)
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
        self._live2d.set_expression(_default_expression())
        if emit_finished and was_active:
            self.playback_finished.emit()
