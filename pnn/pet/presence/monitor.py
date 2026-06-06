"""后台轮询：空闲搭话、挂机轻语。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer

from pnn.pet.presence.config import PresenceConfig, load_presence_config
from pnn.pet.presence.service import get_presence_service
from pnn.pet.reminders.readiness import is_proactive_ready, is_schedule_runtime_ready

logger = logging.getLogger(__name__)


def effective_poll_seconds(cfg: PresenceConfig) -> int:
    """轮询间隔：不超过空闲间隔的一半，避免「改短了仍要等很久才检测」。"""
    poll = max(15, int(cfg.presence_poll_seconds))
    idle = max(60, int(cfg.presence_idle_seconds))
    return min(poll, max(15, idle // 2))


class PresenceMonitor(QObject):
    def __init__(self, *, session_key: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        svc = get_presence_service()
        svc.bind_session(session_key)
        self._svc = svc
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        cfg = load_presence_config()
        self._interval_ms = effective_poll_seconds(cfg) * 1000

    def reload_config(self) -> None:
        cfg = load_presence_config()
        self._interval_ms = effective_poll_seconds(cfg) * 1000
        if self._timer.isActive():
            self._timer.start(self._interval_ms)
        logger.info(
            "PresenceMonitor 已重载：轮询 %ss（空闲间隔 %ss）",
            self._interval_ms // 1000,
            max(60, int(cfg.presence_idle_seconds)),
        )

    def start(self) -> None:
        self._timer.start(self._interval_ms)
        logger.info("PresenceMonitor 启动，轮询 %ss", self._interval_ms // 1000)

    def stop(self) -> None:
        self._timer.stop()

    def _on_tick(self) -> None:
        cfg = load_presence_config()
        if not cfg.presence_enabled or not is_schedule_runtime_ready():
            return
        try:
            if self._svc.tick_idle():
                logger.debug("presence idle nudge fired")
        except Exception:
            logger.exception("Presence tick 失败")
