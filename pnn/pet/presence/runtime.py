"""桌宠在场感运行时：集成 controller / 托盘 / 窗口焦点 / 日程。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QSystemTrayIcon

from pnn.pet.presence.config import load_presence_config
from pnn.pet.presence.monitor import PresenceMonitor
from pnn.pet.presence.service import get_presence_service
from pnn.pet.reminders.auto_trigger import (
    run_auto_triggers_on_window_open,
    run_background_triggers,
    run_overdue_missed_on_ready,
)
from pnn.pet.reminders.manager import get_reminder_manager, session_key_from_character
from pnn.pet.reminders.models import ReminderStatus
from pnn.pet.reminders.readiness import is_proactive_ready

if TYPE_CHECKING:
    from pnn.pet.controller import PetController

logger = logging.getLogger(__name__)


class _ProactiveApiWorker(QThread):
    """后台检查/恢复 API，避免主动搭话阻塞 UI 线程。"""

    finished_ok = Signal(bool, str)

    def __init__(self, text: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._text = text

    def run(self) -> None:
        from pnn.pet.api_guard import ensure_api_before_chat

        ok = ensure_api_before_chat()
        self.finished_ok.emit(ok, self._text)


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
        self._reminder_alarm_retries: dict[str, int] = {}
        self._proactive_queue: list[tuple[str, str]] = []
        self._proactive_retry_timer = QTimer(self)
        self._proactive_retry_timer.setSingleShot(True)
        self._proactive_retry_timer.timeout.connect(self._flush_proactive_queue)
        self._proactive_api_worker: _ProactiveApiWorker | None = None
        self._pending_proactive_kind = ""
        self._pomo_timer = QTimer(self)
        self._pomo_timer.timeout.connect(self._on_pomodoro_tick)

        svc = get_presence_service()
        svc.bind_session(self._session_key)
        svc.touch_session_activity_now()
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
        self._pomo_timer.start(5000)

    def stop(self) -> None:
        self._monitor.stop()
        self._bg_timer.stop()
        self._flash_timer.stop()
        self._pomo_timer.stop()

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
        QTimer.singleShot(0, self._try_fire_due_reminders_now)

    def _try_fire_due_reminders_now(self) -> None:
        try:
            run_background_triggers(
                session_key=self._session_key,
                emit_proactive=self._emit_proactive,
            )
            run_overdue_missed_on_ready(
                session_key=self._session_key,
                emit_proactive=self._emit_proactive,
            )
        except Exception:
            logger.exception("即时日程检测失败")

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

    def _queued_proactive_texts(self) -> set[str]:
        return {text for text, _ in self._proactive_queue}

    def _enqueue_proactive(self, text: str, kind: str) -> None:
        if text in self._queued_proactive_texts():
            return
        self._proactive_queue.append((text, kind))
        get_presence_service().mark_proactive_dispatched()

    def _emit_proactive(self, system_text: str) -> bool:
        text = (system_text or "").strip()
        if not text:
            return False
        kind = get_presence_service().peek_trigger_kind()
        if self._controller.is_busy():
            self._enqueue_proactive(text, kind)
            logger.debug("controller 忙碌，主动对话已排队: %s", text[:40])
            if not self._proactive_retry_timer.isActive():
                self._proactive_retry_timer.start(5000)
            return True
        if not is_proactive_ready(controller_busy=self._controller.is_busy()):
            self._enqueue_proactive(text, kind)
            logger.debug("主动搭话未就绪，已排队: %s", text[:40])
            if not self._proactive_retry_timer.isActive():
                self._proactive_retry_timer.start(5000)
            return True
        self._pending_proactive_kind = kind
        self._start_proactive_dispatch(text, kind)
        return True

    def _start_proactive_dispatch(self, text: str, kind: str = "") -> None:
        if not kind:
            kind = self._pending_proactive_kind or get_presence_service().peek_trigger_kind()
        self._pending_proactive_kind = kind
        worker = self._proactive_api_worker
        if worker is not None and worker.isRunning():
            self._enqueue_proactive(text, kind)
            if not self._proactive_retry_timer.isActive():
                self._proactive_retry_timer.start(5000)
            return
        worker = _ProactiveApiWorker(text, parent=self)
        self._proactive_api_worker = worker
        worker.finished_ok.connect(self._on_proactive_api_ready)
        worker.finished.connect(lambda: self._clear_proactive_api_worker(worker))
        worker.finished.connect(worker.deleteLater)
        get_presence_service().mark_proactive_dispatched()
        worker.start()

    def _clear_proactive_api_worker(self, worker: _ProactiveApiWorker) -> None:
        if self._proactive_api_worker is worker:
            self._proactive_api_worker = None

    def _on_proactive_api_ready(self, ok: bool, text: str) -> None:
        kind = self._pending_proactive_kind
        if not ok:
            self._enqueue_proactive(text, kind)
            self._proactive_retry_timer.start(10000)
            logger.debug("proactive skipped: api unavailable (queued)")
            return
        if self._controller.is_busy():
            self._enqueue_proactive(text, kind)
            if not self._proactive_retry_timer.isActive():
                self._proactive_retry_timer.start(5000)
            return
        if not is_proactive_ready(controller_busy=False):
            self._proactive_queue.insert(0, (text, kind))
            get_presence_service().mark_proactive_dispatched()
            self._proactive_retry_timer.start(5000)
            return
        self._controller.send_proactive(text, trigger_kind=kind)
        get_presence_service().mark_trigger_kind("")
        self._pending_proactive_kind = ""
        logger.info("主动搭话已发送 LLM")
        if self._proactive_queue and not self._controller.is_busy():
            QTimer.singleShot(0, self._flush_proactive_queue)

    def _flush_proactive_queue(self) -> None:
        if self._controller.is_busy():
            if self._proactive_queue:
                self._proactive_retry_timer.start(5000)
            return
        if not self._proactive_queue:
            return
        if not is_proactive_ready(controller_busy=False):
            self._proactive_retry_timer.start(5000)
            return
        text, kind = self._proactive_queue.pop(0)
        self._pending_proactive_kind = kind
        self._start_proactive_dispatch(text, kind)

    @staticmethod
    def _boot_elapsed() -> float:
        from pnn.pet.reminders.readiness import boot_elapsed_seconds

        return boot_elapsed_seconds()

    def _on_startup_delayed(self) -> None:
        try:
            if not is_proactive_ready(controller_busy=self._controller.is_busy()):
                logger.debug("启动日程检测推迟：API/静默期未就绪")
                QTimer.singleShot(5000, self._on_startup_delayed)
                return
            n = run_overdue_missed_on_ready(
                session_key=self._session_key,
                emit_proactive=self._emit_proactive,
            )
            if n > 0:
                logger.debug("启动已派发过期爽约提醒，跳过回归搭话")
                return
            svc = get_presence_service()
            if svc.try_holiday_greeting():
                logger.debug("presence holiday greeting fired")
                return
            if svc.try_session_resume():
                logger.debug("presence session resume fired")
                return
            if svc.try_time_greeting():
                logger.debug("presence time greeting fired")
                return
            if svc.on_startup():
                logger.debug("presence absence-return trigger fired")
        except Exception:
            logger.exception("启动 presence 触发失败")
        finally:
            get_presence_service().arm_idle_monitor()

    def _on_pomodoro_tick(self) -> None:
        try:
            from pnn.pet.presence.pomodoro import get_pomodoro_service

            events = get_pomodoro_service().tick(self._session_key)
            if not events:
                return
            svc = get_presence_service()
            for ev in events:
                svc.on_pomodoro_event(ev)
        except Exception:
            logger.exception("番茄钟 tick 失败")

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
            delta = (r.scheduled_start - now).total_seconds()
            if delta <= 0:
                rid = r.id
                QTimer.singleShot(0, lambda i=rid: self._fire_reminder_alarm(i))
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
            n = run_background_triggers(
                session_key=self._session_key,
                emit_proactive=self._emit_proactive,
            )
            if n == 0:
                mgr = get_reminder_manager()
                r = mgr.get(reminder_id)
                if (
                    r is not None
                    and r.status == ReminderStatus.pending
                    and datetime.now() < r.effective_end()
                ):
                    tries = self._reminder_alarm_retries.get(reminder_id, 0) + 1
                    self._reminder_alarm_retries[reminder_id] = tries
                    if tries <= 18:
                        self._reschedule_background_poll()
                        QTimer.singleShot(
                            10_000,
                            lambda i=reminder_id: self._fire_reminder_alarm(i),
                        )
            else:
                self._reminder_alarm_retries.pop(reminder_id, None)
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
