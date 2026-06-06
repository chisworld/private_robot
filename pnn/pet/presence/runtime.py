"""桌宠在场感运行时：集成 controller / 托盘 / 窗口焦点 / 日程。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QSystemTrayIcon

from pnn.pet.presence.config import load_presence_config
from pnn.pet.presence.monitor import PresenceMonitor
from pnn.pet.presence.service import get_presence_service
from pnn.pet.reminders.auto_trigger import run_auto_triggers_on_window_open, run_background_triggers
from pnn.pet.reminders.manager import get_reminder_manager, session_key_from_character
from pnn.pet.reminders.models import ReminderStatus
from pnn.pet.reminders.readiness import is_proactive_ready

if TYPE_CHECKING:
    from pnn.pet.controller import PetController

logger = logging.getLogger(__name__)


class PresenceRuntime(QObject):
    def __init__(
        self,
        controller: PetController,
        *,
        get_character_id: Callable[[], str],
        tray: QSystemTrayIcon | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._get_character_id = get_character_id
        self._tray = tray
        self._session_key = session_key_from_character(get_character_id())
        self._window_open_handled = False
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._toggle_tray_flash)
        self._flash_visible = True
        self._unread = 0
        self._reminder_alarm_ids: set[str] = set()
        self._reminder_chain_ids: set[str] = set()
        self._proactive_queue: list[str] = []
        self._proactive_retry_timer = QTimer(self)
        self._proactive_retry_timer.setSingleShot(True)
        self._proactive_retry_timer.timeout.connect(self._flush_proactive_queue)

        svc = get_presence_service()
        svc.bind_session(self._session_key)
        svc.wire_dispatch(
            emit_proactive=self._emit_proactive,
            on_unread=self._set_unread_count,
        )
        self._monitor = PresenceMonitor(session_key=self._session_key, parent=self)
        self._bg_timer = QTimer(self)
        self._bg_timer.timeout.connect(self._on_background_tick)

    def set_tray(self, tray: QSystemTrayIcon | None) -> None:
        self._tray = tray

    def start(self) -> None:
        cfg = load_presence_config()
        if not cfg.presence_enabled and not cfg.schedule_background_monitor:
            return
        if cfg.presence_enabled:
            self._monitor.start()
        self._reschedule_background_poll()
        self._schedule_pending_reminder_alarms()
        delay = max(1, int(cfg.schedule_startup_delay_seconds)) * 1000
        QTimer.singleShot(delay, self._on_startup_delayed)

    def stop(self) -> None:
        self._monitor.stop()
        self._bg_timer.stop()
        self._flash_timer.stop()

    def reload_config(self) -> None:
        get_presence_service().reload_config()
        self._monitor.reload_config()
        self._reschedule_background_poll()

    def rebind_character(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
        self._session_key = session_key_from_character(self._get_character_id())
        get_presence_service().bind_session(self._session_key)
        self._monitor = PresenceMonitor(session_key=self._session_key, parent=self)
        cfg = load_presence_config()
        if cfg.presence_enabled:
            self._monitor.start()

    def on_user_message(self, text: str) -> str:
        return get_presence_service().on_user_message(text)

    def schedule_reminder_alarms(self) -> None:
        """用户新建提醒后调用：注册到点一次性定时器。"""
        self._schedule_pending_reminder_alarms()
        self._reschedule_background_poll()

    def on_assistant_reply(self, user_text: str, assistant_text: str) -> None:
        char_name = ""
        try:
            from pnn.characters.service import character_pack_service

            pack = character_pack_service.get_active_pack()
            char_name = str(pack.name if pack else "")
        except Exception:
            pass
        get_presence_service().on_assistant_reply(
            user_text, assistant_text, character_name=char_name
        )

    def on_window_focus(self, focused: bool) -> None:
        get_presence_service().on_window_focus(focused)

    def on_chat_window_shown(self, *, fresh: bool = False) -> None:
        if self._window_open_handled and not fresh:
            return
        self._window_open_handled = True
        self.on_window_focus(True)

        def _run_triggers() -> None:
            if not is_proactive_ready(controller_busy=self._controller.is_busy()):
                logger.debug("窗口打开触发推迟：尚未过启动静默期")
                return
            run_auto_triggers_on_window_open(
                session_key=self._session_key,
                emit_proactive=self._emit_proactive,
                fresh_session=fresh,
            )

        cfg = load_presence_config()
        quiet_ms = max(15, int(cfg.presence_boot_quiet_seconds)) * 1000
        elapsed_ms = int(self._boot_elapsed() * 1000)
        delay = max(0, quiet_ms - elapsed_ms)
        if delay > 0:
            QTimer.singleShot(delay, _run_triggers)
        else:
            _run_triggers()

    def _emit_proactive(self, system_text: str) -> bool:
        text = (system_text or "").strip()
        if not text:
            return False
        if self._controller.is_busy():
            if text not in self._proactive_queue:
                self._proactive_queue.append(text)
                logger.debug("controller 忙碌，主动对话已排队: %s", text[:40])
            if not self._proactive_retry_timer.isActive():
                self._proactive_retry_timer.start(5000)
            return False
        if not is_proactive_ready(controller_busy=self._controller.is_busy()):
            logger.debug("proactive deferred (boot quiet or api)")
            return False
        from pnn.pet.api_guard import ensure_api_before_chat

        if not ensure_api_before_chat():
            logger.debug("proactive skipped: api unavailable")
            return False
        self._controller.send_proactive(text)
        get_presence_service().mark_proactive_dispatched()
        logger.info("主动搭话已发送 LLM")
        return True

    def _flush_proactive_queue(self) -> None:
        while self._proactive_queue and not self._controller.is_busy():
            text = self._proactive_queue.pop(0)
            if not is_proactive_ready(controller_busy=False):
                self._proactive_queue.insert(0, text)
                self._proactive_retry_timer.start(5000)
                return
            from pnn.pet.api_guard import ensure_api_before_chat

            if not ensure_api_before_chat():
                self._proactive_queue.insert(0, text)
                self._proactive_retry_timer.start(10000)
                return
            self._controller.send_proactive(text)
            get_presence_service().mark_proactive_dispatched()
            logger.info("排队主动搭话已发送 LLM")
        if self._proactive_queue:
            self._proactive_retry_timer.start(5000)

    @staticmethod
    def _boot_elapsed() -> float:
        from pnn.pet.reminders.readiness import boot_elapsed_seconds

        return boot_elapsed_seconds()

    def _on_startup_delayed(self) -> None:
        try:
            if not is_proactive_ready(controller_busy=self._controller.is_busy()):
                logger.debug("启动分别检测推迟：API/静默期未就绪")
                return
            if get_presence_service().on_startup():
                logger.debug("presence absence-return trigger fired")
        except Exception:
            logger.exception("启动 presence 触发失败")

    def _on_background_tick(self) -> None:
        try:
            run_background_triggers(
                session_key=self._session_key,
                emit_proactive=self._emit_proactive,
            )
            self._reschedule_background_poll()
        except Exception:
            logger.exception("后台日程轮询失败")

    def _has_upcoming_reminders(self) -> bool:
        mgr = get_reminder_manager()
        now = datetime.now()
        horizon = now + timedelta(hours=24)
        for r in mgr.list_for_session(self._session_key, status=ReminderStatus.pending):
            if r.start_notified_at is not None:
                continue
            if r.scheduled_start <= horizon:
                return True
        return False

    def _reschedule_background_poll(self) -> None:
        cfg = load_presence_config()
        if not cfg.schedule_background_monitor:
            return
        poll = max(300, int(cfg.schedule_background_poll_seconds))
        if self._has_upcoming_reminders():
            poll = min(poll, 30)
        self._bg_timer.start(poll * 1000)

    def _schedule_pending_reminder_alarms(self) -> None:
        mgr = get_reminder_manager()
        now = datetime.now()
        for r in mgr.list_for_session(self._session_key, status=ReminderStatus.pending):
            if r.id in self._reminder_alarm_ids:
                continue
            if r.start_notified_at is not None:
                continue
            delta = (r.scheduled_start - now).total_seconds()
            if delta <= 0:
                continue
            if delta > 86400:
                if r.id in self._reminder_chain_ids:
                    continue
                self._reminder_chain_ids.add(r.id)
                QTimer.singleShot(
                    86400000,
                    lambda i=r.id: self._reminder_alarm_chain_tick(i),
                )
                continue
            self._reminder_alarm_ids.add(r.id)
            delay_ms = max(0, int(delta * 1000))
            rid = r.id
            QTimer.singleShot(delay_ms, lambda i=rid: self._fire_reminder_alarm(i))

    def _reminder_alarm_chain_tick(self, reminder_id: str) -> None:
        self._reminder_chain_ids.discard(reminder_id)
        self._schedule_pending_reminder_alarms()

    def _fire_reminder_alarm(self, reminder_id: str) -> None:
        self._reminder_alarm_ids.discard(reminder_id)
        try:
            run_background_triggers(
                session_key=self._session_key,
                emit_proactive=self._emit_proactive,
            )
        except Exception:
            logger.exception("到点提醒触发失败: %s", reminder_id)

    def _set_unread_count(self, count: int) -> None:
        self._unread = max(0, int(count))
        if self._tray is None:
            return
        tip = "14酱桌宠"
        if self._unread > 0:
            tip = f"({self._unread}) 有新消息"
        self._tray.setToolTip(tip)
        if self._unread > 0:
            if not self._flash_timer.isActive():
                self._flash_timer.start(600)
        else:
            self._flash_timer.stop()
            self._tray.setVisible(True)

    def _toggle_tray_flash(self) -> None:
        if self._tray is None or self._unread <= 0:
            return
        self._flash_visible = not self._flash_visible
        self._tray.setVisible(self._flash_visible)
