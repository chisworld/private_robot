"""ASR WebSocket 会话（对接 /ws/asr + /api/stream/start）。"""

from __future__ import annotations

import json
import logging
import time

from PySide6.QtCore import QObject, Signal
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
        if self._active:
            return
        self.hint_changed.emit(_STATUS_HINT["loading"])
        try:
            info = self._api.asr_stream_start()
            logger.info("ASR stream start: %s", info)
        except Exception as exc:
            self.error_occurred.emit(str(exc))
            self.hint_changed.emit("")
            return

        if not _ws_is_connected(self._ws):
            self._ws.open(self._ws_url)
        self._active = True
        self.status_changed.emit("loading")

    def stop(self) -> None:
        if not self._active:
            return
        self._api.asr_stream_stop()
        if _ws_is_connected(self._ws):
            self._ws.close()
        self._active = False
        self._ws_ready = False
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
