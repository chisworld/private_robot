"""后台预热 API / TTS，不阻塞桌宠窗口显示。"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QThread, Signal

from pnn.pet.api_client import PetApiClient

logger = logging.getLogger(__name__)


class ServiceWarmupWorker(QThread):
    """人物窗出现后立即在后台等 API + TTS 推理预热完成。"""

    status_changed = Signal(str, bool)
    finished_ok = Signal(bool)

    TTS_WAIT_TIMEOUT = 120.0
    API_WAIT_TIMEOUT = 45.0

    def __init__(self, api: PetApiClient, parent=None) -> None:
        super().__init__(parent)
        self._api = api

    def run(self) -> None:
        deadline = time.monotonic() + self.API_WAIT_TIMEOUT
        while time.monotonic() < deadline:
            if self._api.health(timeout=1.5):
                break
            self.status_changed.emit("等待 API 启动 (8765)…", False)
            time.sleep(0.8)
        else:
            self.status_changed.emit("API 未启动 (8765)", True)
            self.finished_ok.emit(False)
            return

        if self._api.wait_tts_ready(timeout=2.0, poll=0.25):
            self.status_changed.emit("TTS 已就绪", False)
            self.finished_ok.emit(True)
            return

        self.status_changed.emit("TTS 预热中（权重 + 推理，约 1～8 分钟）…", False)
        try:
            self._api.kick_tts_warmup()
        except Exception as exc:
            logger.warning("TTS 预热请求失败: %s", exc)

        def _on_progress(msg: str, _pct: int) -> None:
            if msg.strip():
                self.status_changed.emit(msg, False)

        ok = self._api.ensure_tts_ready(
            timeout=self.TTS_WAIT_TIMEOUT,
            on_progress=_on_progress,
            require_inference=False,
            kick_warmup=False,
        )
        if ok:
            self.status_changed.emit("TTS 已就绪，可使用语音回复", False)
            self.finished_ok.emit(True)
            return

        h = self._api.tts_health(timeout=5.0)
        if h.get("server_alive"):
            self.status_changed.emit("TTS 仍在加载，首次语音可能稍慢…", False)
            self.finished_ok.emit(True)
            return

        self.status_changed.emit("TTS 未就绪，请检查 GPT-SoVITS / 设置页 TTS", True)
        self.finished_ok.emit(False)
