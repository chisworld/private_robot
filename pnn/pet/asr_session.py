"""ASR WebSocket 会话（对接 /ws/asr + /api/stream/start）。"""

from __future__ import annotations

import json
import logging
import time

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

from pnn.pet.api_client import PetApiClient

logger = logging.getLogger(__name__)

_STATUS_HINT = {
    "loading": "正在加载语音识别…",
    "listening": "请对着麦克风说话…",
    "speech": "正在听…",
    "idle": "",
    "error": "",
}


def _ws_is_connected(ws: QWebSocket) -> bool:
    """PySide6 中 QWebSocket 使用 QAbstractSocket.SocketState，无 QWebSocket.SocketState。"""
    return ws.state() == QAbstractSocket.SocketState.ConnectedState


class _AsrStartWorker(QThread):
    finished_ok = Signal(int, dict)
    failed = Signal(int, str)

    def __init__(
        self,
        api: PetApiClient,
        run_id: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._run_id = run_id

    def run(self) -> None:
        try:
            from pnn.core.api_health import ensure_api_for_pet, is_api_ready_for_pet

            if not is_api_ready_for_pet(timeout=1.0):
                if not ensure_api_for_pet(timeout=60.0):
                    self.failed.emit(
                        self._run_id,
                        "API 8765 未就绪，请先运行 scripts/start.bat 或稍后再试",
                    )
                    return
            info = self._api.asr_stream_start()
            self.finished_ok.emit(self._run_id, info)
        except Exception as exc:
            self.failed.emit(self._run_id, str(exc))


class AsrSession(QObject):
    """麦克风流式识别；final 文本通过信号交给桌宠发送。"""

    status_changed = Signal(str)
    partial_changed = Signal(str)
    final_text = Signal(str)
    error_occurred = Signal(str)
    hint_changed = Signal(str)
    level_changed = Signal(float, float, bool)  # energy, threshold, is_speech

    def __init__(self, api: PetApiClient, ws_url: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._ws_url = ws_url or api.ws_url
        self._ws = QWebSocket()
        self._ws.textMessageReceived.connect(self._on_message)
        self._ws.connected.connect(self._on_ws_connected)
        self._ws.disconnected.connect(self._on_ws_disconnected)
        self._ws.errorOccurred.connect(self._on_ws_error)
        self._active = False
        self._starting = False
        self._run_id = 0
        self._ws_ready = False
        self._last_partial = ""
        self._last_partial_emit = 0.0
        self._partial_min_interval = 0.08
        self._level_meter_enabled = False

    def set_level_meter_enabled(self, enabled: bool) -> None:
        """仅设置页麦克风测试需要 level 信号时开启。"""
        self._level_meter_enabled = bool(enabled)

    def is_active(self) -> bool:
        return self._active

    def toggle(self) -> None:
        if self._active:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self._active or self._starting:
            return
        self._starting = True
        self._run_id += 1
        run_id = self._run_id
        self.hint_changed.emit(_STATUS_HINT["loading"])
        if not _ws_is_connected(self._ws):
            self._ws.open(self._ws_url)
        worker = _AsrStartWorker(self._api, run_id, parent=self)
        worker.finished_ok.connect(self._on_start_ok)
        worker.failed.connect(self._on_start_fail)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_start_ok(self, run_id: int, info: dict) -> None:
        if run_id != self._run_id:
            return
        self._starting = False
        logger.info("ASR stream start: %s", info)
        if not _ws_is_connected(self._ws):
            self._ws.open(self._ws_url)
        self._active = True
        self.status_changed.emit(str(info.get("status") or "loading"))

    def _on_start_fail(self, run_id: int, message: str) -> None:
        if run_id != self._run_id:
            return
        self._starting = False
        self.error_occurred.emit(message)
        self.hint_changed.emit("")

    def stop(self, *, stop_backend: bool = True) -> None:
        """关闭会话；stop_backend=False 时仅断开 WS（设置页探针让位给对话窗）。"""
        self._run_id += 1
        self._starting = False
        was_active = self._active
        self._active = False
        self._ws_ready = False
        if stop_backend:
            try:
                self._api.asr_stream_stop()
            except Exception as exc:
                logger.debug("ASR stream stop: %s", exc)
        if _ws_is_connected(self._ws):
            self._ws.close()
        if was_active or stop_backend:
            self.partial_changed.emit("")
            self.hint_changed.emit("")
            self.status_changed.emit("idle")

    def _on_ws_connected(self) -> None:
        self._ws_ready = True
        logger.info("ASR WebSocket 已连接")

    def _on_ws_disconnected(self) -> None:
        self._ws_ready = False
        if self._active:
            self.error_occurred.emit("语音识别连接已断开")
            self._active = False
            self.hint_changed.emit("")
            self.status_changed.emit("idle")

    def _on_ws_error(self, _code) -> None:
        err = self._ws.errorString() or "WebSocket 错误"
        logger.warning("ASR WS: %s", err)
        if self._active:
            self.error_occurred.emit(err)

    def _on_message(self, payload: str) -> None:
        try:
            msg = json.loads(payload)
        except json.JSONDecodeError:
            return
        t = msg.get("type")
        if t == "status":
            status = str(msg.get("status", ""))
            self.status_changed.emit(status)
            hint = _STATUS_HINT.get(status, "")
            if hint:
                self.hint_changed.emit(hint)
            elif status == "idle":
                self.hint_changed.emit("")
        elif t == "partial":
            text = str(msg.get("text", ""))
            now = time.monotonic()
            if (
                text != self._last_partial
                and now - self._last_partial_emit >= self._partial_min_interval
            ):
                self._last_partial = text
                self._last_partial_emit = now
                self.partial_changed.emit(text)
            if text.strip():
                self.hint_changed.emit(text)
        elif t == "final":
            text = str(msg.get("text", "")).strip()
            if text:
                self.final_text.emit(text)
        elif t == "level":
            if not self._level_meter_enabled:
                return
            self.level_changed.emit(
                float(msg.get("energy", 0)),
                float(msg.get("threshold", 0.03)),
                bool(msg.get("is_speech", False)),
            )
        elif t == "error":
            self.error_occurred.emit(str(msg.get("message", "ASR error")))
