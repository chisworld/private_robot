from __future__ import annotations

from datetime import datetime, timedelta

from pnn.pet.reminders.models import Reminder, ReminderStatus
from pnn.pet.reminders.store import load_reminders, save_reminders


def session_key_from_character(char_id: str) -> str:
    cid = (char_id or "").strip()
    return f"character:{cid}" if cid else "__default__"


class ReminderManager:
    def __init__(self) -> None:
        self._items: list[Reminder] | None = None

    def _ensure_loaded(self) -> list[Reminder]:
        if self._items is None:
            self._items = load_reminders()
        return self._items

    def _persist(self) -> None:
        save_reminders(self._ensure_loaded())

    def reload(self) -> None:
        self._items = load_reminders()

    def list_all(self) -> list[Reminder]:
        return list(self._ensure_loaded())

    def list_for_session(
        self,
        session_key: str,
        *,
        status: ReminderStatus | None = None,
    ) -> list[Reminder]:
        items = [
            r
            for r in self._ensure_loaded()
            if r.session_key == session_key and (status is None or r.status == status)
        ]
        return sorted(items, key=lambda r: r.scheduled_start)

    def get(self, reminder_id: str) -> Reminder | None:
        rid = (reminder_id or "").strip()
        for r in self._ensure_loaded():
            if r.id == rid:
                return r
        return None

    def create(
        self,
        *,
        session_key: str,
        title: str,
        scheduled_start: datetime,
        scheduled_end: datetime | None = None,
        character_name: str = "",
        description: str = "",
        source: str = "manual",
    ) -> Reminder:
        text = (title or "").strip()
        if not text:
            raise ValueError("title 不能为空")
        end = scheduled_end or (scheduled_start + timedelta(hours=1))
        reminder = Reminder(
            session_key=session_key,
            title=text,
            description=(description or "").strip(),
            character_name=(character_name or "").strip(),
            scheduled_start=scheduled_start,
            scheduled_end=end,
            source=source,
        )
        self._ensure_loaded().append(reminder)
        self._persist()
        return reminder

    def mark_completed(self, reminder_id: str) -> Reminder | None:
        r = self.get(reminder_id)
        if r is None:
            return None
        r.status = ReminderStatus.completed
        r.completed_at = datetime.now()
        self._persist()
        return r

    def mark_cancelled(self, reminder_id: str) -> Reminder | None:
        r = self.get(reminder_id)
        if r is None:
            return None
        r.status = ReminderStatus.cancelled
        self._persist()
        return r

    def delete(self, reminder_id: str) -> bool:
        rid = (reminder_id or "").strip()
        items = self._ensure_loaded()
        before = len(items)
        self._items = [r for r in items if r.id != rid]
        if len(self._items) == before:
            return False
        self._persist()
        return True

    def find_open_triggers(
        self,
        session_key: str,
        now: datetime | None = None,
        *,
        nudge_during_window: bool = True,
    ) -> list[tuple[Reminder, str]]:
        ts = now or datetime.now()
        out: list[tuple[Reminder, str]] = []
        for r in self.list_for_session(session_key, status=ReminderStatus.pending):
            if r.triggered_at is not None:
                continue
            end = r.effective_end()
            if ts >= end:
                out.append((r, "missed"))
            elif nudge_during_window and r.scheduled_start <= ts < end:
                out.append((r, "nudge"))
        return out

    def find_background_triggers(
        self,
        session_key: str,
        now: datetime | None = None,
    ) -> list[tuple[Reminder, str]]:
        ts = now or datetime.now()
        out: list[tuple[Reminder, str]] = []
        for r in self.list_for_session(session_key, status=ReminderStatus.pending):
            end = r.effective_end()
            if ts >= end and r.triggered_at is None:
                out.append((r, "missed"))
            elif r.start_notified_at is None and r.scheduled_start <= ts < end:
                out.append((r, "due_start"))
        return out

    def mark_start_notified(self, reminder: Reminder) -> None:
        reminder.start_notified_at = datetime.now()
        self._persist()

    def mark_triggered(self, reminder: Reminder, *, as_missed: bool) -> None:
        reminder.triggered_at = datetime.now()
        if as_missed:
            reminder.status = ReminderStatus.missed
        self._persist()


_singleton: ReminderManager | None = None


def get_reminder_manager() -> ReminderManager:
    global _singleton
    if _singleton is None:
        _singleton = ReminderManager()
    return _singleton
