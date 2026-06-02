"""桌宠对话编排：LLM 流式 → 表情 → TTS 口型。"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QElapsedTimer, QThread, QTimer, Signal

from pnn.pet.api_client import ChatMessage, PetApiClient
from pnn.pet.audio import LipSyncPlayer
from pnn.pet.console_log import log_ai_reply, log_tts
from pnn.pet.expression_catalog import build_llm_expression_instruction, discover_expression_names
from pnn.pet.expression_tags import (
    parse_tagged_piece,
    pull_final_tagged_chunk,
    pull_tagged_tts_chunks,
    strip_expression_tags,
)
from pnn.pet.paths import DEFAULT_EXPRESSION

if TYPE_CHECKING:
    from pnn.pet.live2d_widget import Live2DWidget

logger = logging.getLogger(__name__)

# 分句模式下同时向 TTS 提交的合成任务数（过大易占满 CPU/GPU 导致界面卡顿）
MAX_TTS_SYNTH_PARALLEL = 1
# 对话历史上限（条），避免请求体与内存无限增长
MAX_HISTORY_MESSAGES = 40


def _start_thread(worker: QThread) -> None:
    """子线程结束后自动 deleteLater，避免 QThread 对象堆积导致卡顿。"""
    worker.finished.connect(worker.deleteLater)
    worker.start()


class _ChatWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)
    delta_changed = Signal(str)

    def __init__(
        self,
        api: PetApiClient,
        message: str,
        history: list[ChatMessage],
        *,
        stream_deltas: bool,
        pet_expression_prompt: str | None = None,
        cancel: threading.Event | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._message = message
        self._history = history
        self._stream_deltas = stream_deltas
        self._pet_expression_prompt = pet_expression_prompt
        self._cancel = cancel

    def run(self) -> None:
        preview = self._message.replace("\n", " ")[:120]
        print(f"[pet-llm] 用户: {preview}", flush=True)

        def on_delta(full: str) -> None:
            if self._cancel is not None and self._cancel.is_set():
                return
            self.delta_changed.emit(full)

        result = self._api.stream_chat(
            self._message,
            self._history,
            on_delta=on_delta if self._stream_deltas else None,
            pet_expression_prompt=self._pet_expression_prompt,
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

            if translate_service.is_enabled():
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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._text = text
        self._cancel = cancel

    def run(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            return
        preview = self._text.replace("\n", " ")[:40]
        log_tts("合成", f"开始 {preview}")
        try:
            data = self._api.synthesize_tts(
                self._text,
                log_progress=False,
                cancel=self._cancel,
            )
            if self._cancel is not None and self._cancel.is_set():
                return
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


class PetController(QObject):
    """连接 API、Live2D 与双窗口 UI。"""

    status_changed = Signal(str, bool)
    bubble_changed = Signal(str)
    tts_synth_progress = Signal(str, int)
    playback_started = Signal()
    playback_finished = Signal()
    loading_changed = Signal(bool)

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
        self._answer_text = ""
        self._playback_seq = 0
        self._tts_speak_mode = "full"
        self._tts_spoken_offset = 0
        self._playback_active = False
        self._turn_id = 0

        # 整段朗读
        self._full_tts_queue: list[tuple[str, str]] = []
        self._full_tts_busy = False
        self._full_tts_expr = DEFAULT_EXPRESSION

        # 分句朗读：并行合成 + 按序播放
        self._seg_texts: list[str] = []
        self._seg_exprs: list[str] = []
        self._seg_audio: dict[int, bytes] = {}
        self._seg_synth: set[int] = set()

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
        self._display_answer_text = ""
        self._play_queue: list[_PlayItem] = []
        self._translate_worker: _TranslateWorker | None = None
        self._bubble_translate_seq = 0
        self._last_user_msg = ""

        self._mouth_timer = QTimer(self)
        self._mouth_timer.setInterval(16)
        self._mouth_timer.timeout.connect(self._poll_mouth)

        self._playback_poll = QTimer(self)
        self._playback_poll.setInterval(80)
        self._playback_poll.timeout.connect(self._tick_playback_poll)
        self._playback_poll_on_end = None

    def set_tts_speak_mode(self, mode: str) -> None:
        m = (mode or "full").strip().lower()
        self._tts_speak_mode = m if m in ("sentence", "full") else "full"

    def _is_stale_turn(self, turn: int) -> bool:
        return turn != self._turn_id

    def _sync_pipeline_status(self, *, is_err: bool = False) -> None:
        """状态栏与终端日志对齐：播放优先于合成。"""
        if self._playback_active:
            self._emit_status("播放中…", is_err)
            return
        if self._full_tts_busy or self._seg_synth:
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
        if self._tts_speak_mode != "sentence":
            return False
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
        if self._tts_speak_mode == "sentence":
            return self._pipeline_active()
        return (
            self._full_tts_busy
            or bool(self._full_tts_queue)
            or self._playback_active
        )

    def prepare(self) -> bool:
        if not self._api.health():
            self._emit_status("API 未启动 (8765)", True)
            return False
        return True

    def _ensure_expression_catalog(self) -> None:
        if self._expr_names is not None:
            return
        self._expr_names = discover_expression_names()
        self._expr_available = set(self._expr_names)
        self._pet_expr_prompt = build_llm_expression_instruction(self._expr_names)

    def _trim_history(self) -> None:
        if len(self._history) > MAX_HISTORY_MESSAGES:
            del self._history[: len(self._history) - MAX_HISTORY_MESSAGES]

    def _reset_tts_state(self) -> None:
        self._play_queue.clear()
        self._full_tts_queue.clear()
        self._full_tts_busy = False
        self._seg_texts.clear()
        self._seg_exprs.clear()
        self._seg_audio.clear()
        self._seg_synth.clear()
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
            self.bubble_changed.emit("")

    def send_message(self, text: str, *, interrupt: bool = False) -> None:
        msg = text.strip()
        if not msg:
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
        self.bubble_changed.emit("…")
        self._last_delta_len = 0
        self._delta_throttle.restart()
        self._emit_status("思考中…", False)
        self._history.append(ChatMessage(role="user", content=msg))
        self._last_user_msg = msg
        self._trim_history()
        self._ensure_expression_catalog()

        stream = self._tts_speak_mode == "sentence"
        worker = _ChatWorker(
            self._api,
            msg,
            self._history[:-1],
            stream_deltas=stream,
            pet_expression_prompt=self._pet_expr_prompt,
            cancel=self._stream_cancel,
            parent=self,
        )
        self._chat_worker = worker
        worker.failed.connect(lambda err: self._on_chat_failed(err, turn))
        worker.finished_ok.connect(lambda full: self._on_chat_done(full, turn))
        if stream:
            worker.delta_changed.connect(lambda full: self._on_chat_delta(full, turn))
        _start_thread(worker)

    def _on_chat_delta(self, full: str, turn: int) -> None:
        if turn != self._turn_id:
            return
        self._raw_answer_text = full
        self._answer_text = strip_expression_tags(full)
        self._display_answer_text = self._answer_text
        if self._tts_speak_mode == "full":
            n = len(self._display_answer_text)
            if (
                n - self._last_delta_len >= 12
                or self._delta_throttle.hasExpired(120)
            ):
                self._last_delta_len = n
                self._delta_throttle.restart()
                self.bubble_changed.emit(self._display_answer_text)
        chunks, self._tts_spoken_offset, self._stream_last_expr = pull_tagged_tts_chunks(
            full,
            self._tts_spoken_offset,
            available=self._expr_available,
            last_expr=self._stream_last_expr,
        )
        for expr, piece in chunks:
            self._enqueue_tts(piece, expr)

    def _on_chat_failed(self, err: str, turn: int) -> None:
        if turn != self._turn_id:
            return
        self._loading = False
        self.loading_changed.emit(False)
        self.bubble_changed.emit("")
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
        log_ai_reply(clean, expression=self._stream_last_expr or DEFAULT_EXPRESSION)
        self._notify_memory_turn(self._last_user_msg, clean)

        if clean:
            if self._tts_speak_mode == "full":
                self._update_display_bubble(clean, turn)
        else:
            self.bubble_changed.emit("")

        has_tts = bool(clean.strip())
        if self._tts_speak_mode == "full":
            if has_tts:
                self._sync_pipeline_status()
                expr, _ = parse_tagged_piece(
                    full,
                    available=self._expr_available,
                    last_expr=self._stream_last_expr,
                )
                self._enqueue_tts(clean, expr)
            else:
                self.playback_finished.emit()
        else:
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
                    expr, piece = tail_pack
                    if not (self._seg_texts and self._seg_texts[-1] == piece):
                        self._enqueue_tts(piece, expr)
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

        threading.Thread(target=_run, daemon=True, name="pet-memory-turn").start()

    def _update_display_bubble(self, text: str, turn: int) -> None:
        self._schedule_display_translate(text, turn)

    def _show_segment_bubble(self, text: str, turn: int) -> None:
        """分句朗读：先显示当前句原文，再异步翻译为气泡中文。"""
        piece = (text or "").strip()
        if not piece or self._is_stale_turn(turn):
            return
        self._bubble_translate_seq += 1
        seq = self._bubble_translate_seq
        self.bubble_changed.emit(piece)
        self._schedule_display_translate(piece, turn, bubble_seq=seq)

    def _enqueue_tts(self, text: str, expression: str | None = None) -> None:
        piece = text.strip()
        if not piece:
            return
        expr = (expression or DEFAULT_EXPRESSION).strip()
        if self._tts_speak_mode == "sentence":
            self._enqueue_seg(piece, expr)
        else:
            self._full_tts_queue.append((piece, expr))
            if not self._full_tts_busy:
                self._sync_pipeline_status()
                self._start_full_tts()

    def _schedule_display_translate(
        self,
        text: str,
        turn: int,
        *,
        bubble_seq: int | None = None,
    ) -> None:
        try:
            from pnn.translate.service import translate_service

            if not translate_service.is_enabled():
                self.bubble_changed.emit(text)
                return
        except Exception:
            self.bubble_changed.emit(text)
            return

        if self._translate_worker is not None and self._translate_worker.isRunning():
            self._translate_worker.wait(200)
        worker = _TranslateWorker(text, parent=self)
        self._translate_worker = worker

        def _apply(translated: str) -> None:
            if turn != self._turn_id:
                return
            if bubble_seq is not None and bubble_seq != self._bubble_translate_seq:
                return
            self._display_answer_text = translated
            self.bubble_changed.emit(translated)

        worker.finished_ok.connect(_apply)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _enqueue_seg(self, text: str, expression: str) -> None:
        self._seg_texts.append(text)
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
                else DEFAULT_EXPRESSION
            )
            self._live2d.set_expression(expr)
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

    def _start_full_tts(self) -> None:
        if not self._full_tts_queue:
            self._full_tts_busy = False
            if not self._playback_active:
                self._sync_pipeline_status()
            return
        text, expr = self._full_tts_queue.pop(0)
        turn = self._turn_id
        self._full_tts_busy = True
        self._full_tts_expr = expr
        self._show_tts_synth(text, 5)
        worker = _TtsWorker(self._api, text, cancel=self._stream_cancel, parent=self)
        worker.progress_changed.connect(self._on_tts_worker_progress)
        worker.finished_ok.connect(lambda wav: self._on_full_tts_ready(wav, turn))
        worker.failed.connect(lambda err: self._on_full_tts_failed(err, turn))
        _start_thread(worker)

    def _show_tts_synth(self, text: str, percent: int) -> None:
        del text, percent
        # 合成阶段不刷新气泡，避免与播放中的句子叠成两个框

    def _on_tts_worker_progress(self, message: str, percent: int) -> None:
        self.tts_synth_progress.emit(message, percent)

    def _clear_tts_synth_ui(self) -> None:
        self.tts_synth_progress.emit("", -1)

    def _on_full_tts_failed(self, err: str, turn: int) -> None:
        self._full_tts_busy = False
        if self._is_stale_turn(turn):
            return
        self._full_tts_queue.clear()
        self._emit_status(f"TTS: {err}", True)
        self.playback_finished.emit()

    def _on_full_tts_ready(self, wav: bytes, turn: int) -> None:
        self._full_tts_busy = False
        if self._is_stale_turn(turn):
            return
        text = self._answer_text
        self._live2d.set_expression(self._full_tts_expr)
        print(f"[pet-ai] 整段表情: {self._full_tts_expr}", flush=True)
        self._play_audio(text, wav, on_end=self._on_full_play_ended)

    def _on_full_play_ended(self) -> None:
        if self._full_tts_queue:
            self._start_full_tts()
            return
        self._finish_all_playback()

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
        on_end = self._playback_poll_on_end
        self._playback_poll_on_end = None
        if on_end is not None and seq == self._playback_seq:
            on_end()

    def _finish_all_playback(self) -> None:
        self._play_queue.clear()
        self._reset_tts_state()
        self._sync_pipeline_status()
        log_tts("播放", "全部语音播放结束")
        self.bubble_changed.emit("")
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
        if emit_finished and was_active:
            self.playback_finished.emit()
