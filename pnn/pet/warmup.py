"""后台预热 API / TTS，不阻塞桌宠窗口显示。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from pnn.pet.api_client import PetApiClient

logger = logging.getLogger(__name__)


class ServiceWarmupWorker(QThread):
    """后台等待 API 侧 TTS 预热（启动时 server 已 preload，此处最多等 120s）。"""

    status_changed = Signal(str, bool)
    finished_ok = Signal(bool)

    # 含权重切换 + 首次试合成，冷启动可能 3～8 分钟
    TTS_WAIT_TIMEOUT = 480.0

    def __init__(self, api: PetApiClient, parent=None) -> None:
        super().__init__(parent)
        self._api = api

    def run(self) -> None:
        if not self._api.health():
            self.status_changed.emit("API 未启动 (8765)", True)
            self.finished_ok.emit(False)
            return

        if self._api.wait_tts_ready(timeout=2.0, poll=0.25):
            self.status_changed.emit("TTS 已就绪", False)
            self.finished_ok.emit(True)
            return

        self.status_changed.emit("TTS 预热中（权重 + 推理试合成，约 1～8 分钟）…", False)
        try:
            self._api.kick_tts_warmup()
        except Exception as exc:
            logger.warning("TTS 预热请求失败: %s", exc)

        if self._api.wait_tts_ready(timeout=self.TTS_WAIT_TIMEOUT, poll=1.0):
            self.status_changed.emit("TTS 已就绪，可使用语音回复", False)
            self.finished_ok.emit(True)
            return

        h = self._api.tts_health(timeout=5.0)
        if h.get("server_alive"):
            if h.get("warming"):
                self.status_changed.emit(
                    "TTS 推理预热中，首次语音约 1～8 分钟…", False
                )
            else:
                self.status_changed.emit(
                    "TTS 服务在线，首次对话将加载模型…", False
                )
            self.finished_ok.emit(True)
            return

        self.status_changed.emit("TTS 未就绪，请检查 GPT-SoVITS / 设置页 TTS", True)
        self.finished_ok.emit(False)
