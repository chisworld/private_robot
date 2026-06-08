"""日程生命周期：到点提醒删除、过期爽约抱怨后删除。"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from pnn.pet.reminders.auto_trigger import (
    build_reminder_trigger_text,
    run_background_triggers,
    run_overdue_missed_on_ready,
)
from pnn.pet.reminders.manager import get_reminder_manager, session_key_from_character
from pnn.pet.reminders.models import ReminderStatus


def test_purge_ended_removes_missed_but_keeps_pending_until_trigger(isolated_presence_data):
    mgr = get_reminder_manager()
    sk = session_key_from_character("test")
    now = datetime(2026, 6, 7, 21, 0, 0)
    past = mgr.create(
        session_key=sk,
        title="煮饭",
        scheduled_start=now - timedelta(hours=1),
        scheduled_end=now - timedelta(minutes=30),
    )
    past.status = ReminderStatus.missed
    past.triggered_at = now - timedelta(minutes=20)
    mgr._persist()

    pending_past = mgr.create(
        session_key=sk,
        title="鸣潮",
        scheduled_start=now - timedelta(minutes=40),
        scheduled_end=now - timedelta(minutes=10),
    )

    removed = mgr.purge_ended_reminders(sk, now=now)
    assert removed == 1
    left = mgr.list_for_session(sk)
    assert len(left) == 1
    assert left[0].id == pending_past.id


def test_missed_trigger_deletes_reminder(isolated_presence_data, monkeypatch):
    mgr = get_reminder_manager()
    sk = session_key_from_character("test")
    now = datetime(2026, 6, 7, 21, 0, 0)
    rem = mgr.create(
        session_key=sk,
        title="鸣潮",
        scheduled_start=now - timedelta(minutes=35),
        scheduled_end=now - timedelta(minutes=5),
    )

    emitted: list[str] = []

    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.is_schedule_runtime_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.build_presence_trigger",
        lambda *a, **k: "",
    )
    presence = MagicMock()
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.get_presence_service",
        lambda: presence,
    )

    def emit(text: str) -> bool:
        emitted.append(text)
        return True

    n = run_overdue_missed_on_ready(session_key=sk, emit_proactive=emit, now=now)
    assert n == 1
    assert emitted
    missed_text = build_reminder_trigger_text(rem, "missed")
    assert "未打开桌宠" in missed_text
    assert mgr.get(rem.id) is None
    presence.on_missed_appointment.assert_called_once_with("鸣潮")


def test_due_start_deletes_reminder_on_success(isolated_presence_data, monkeypatch):
    mgr = get_reminder_manager()
    sk = session_key_from_character("test")
    now = datetime(2026, 6, 7, 21, 0, 0)
    rem = mgr.create(
        session_key=sk,
        title="鸣潮",
        scheduled_start=now - timedelta(minutes=2),
        scheduled_end=now + timedelta(minutes=28),
    )

    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.load_presence_config",
        lambda: type("C", (), {"schedule_background_monitor": True})(),
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.is_schedule_runtime_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.build_presence_trigger",
        lambda *a, **k: "",
    )

    n = run_background_triggers(
        session_key=sk,
        emit_proactive=lambda _t: True,
        now=now,
    )
    assert n == 1
    assert mgr.get(rem.id) is None


def test_due_start_not_deleted_when_emit_fails(isolated_presence_data, monkeypatch):
    mgr = get_reminder_manager()
    sk = session_key_from_character("test")
    now = datetime(2026, 6, 7, 21, 0, 0)
    rem = mgr.create(
        session_key=sk,
        title="鸣潮",
        scheduled_start=now - timedelta(minutes=2),
        scheduled_end=now + timedelta(minutes=28),
    )

    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.load_presence_config",
        lambda: type("C", (), {"schedule_background_monitor": True})(),
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.is_schedule_runtime_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.build_presence_trigger",
        lambda *a, **k: "",
    )

    n = run_background_triggers(
        session_key=sk,
        emit_proactive=lambda _t: False,
        now=now,
    )
    assert n == 0
    assert mgr.get(rem.id) is not None


def test_due_start_auto_launches_bound_app(isolated_presence_data, monkeypatch):
    mgr = get_reminder_manager()
    sk = session_key_from_character("test")
    now = datetime(2026, 6, 7, 21, 0, 0)
    rem = mgr.create(
        session_key=sk,
        title="玩鸣潮",
        scheduled_start=now - timedelta(minutes=2),
        scheduled_end=now + timedelta(minutes=28),
        launch_app_id="wuthering",
    )

    launched: list[str] = []

    def fake_launch(args):
        launched.append(str(args.get("app")))
        return "已启动"

    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.load_presence_config",
        lambda: type("C", (), {"schedule_background_monitor": True})(),
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.is_schedule_runtime_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.build_presence_trigger",
        lambda *a, **k: "",
    )
    monkeypatch.setattr(
        "pnn.launch_apps.service.launch_apps_service.call_launch_app",
        fake_launch,
    )

    n = run_background_triggers(
        session_key=sk,
        emit_proactive=lambda _t: True,
        now=now,
    )
    assert n == 1
    assert launched == ["wuthering"]
    assert mgr.get(rem.id) is None


def test_due_start_success_no_missed_after_window(isolated_presence_data, monkeypatch):
    mgr = get_reminder_manager()
    sk = session_key_from_character("test")
    start = datetime(2026, 6, 7, 21, 0, 0)
    end = start + timedelta(minutes=30)
    rem = mgr.create(
        session_key=sk,
        title="鸣潮",
        scheduled_start=start,
        scheduled_end=end,
    )

    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.load_presence_config",
        lambda: type("C", (), {"schedule_background_monitor": True})(),
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.is_schedule_runtime_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.build_presence_trigger",
        lambda *a, **k: "",
    )

    run_background_triggers(
        session_key=sk,
        emit_proactive=lambda _t: True,
        now=start + timedelta(minutes=1),
    )
    assert mgr.get(rem.id) is None

    emitted: list[str] = []
    n = run_overdue_missed_on_ready(
        session_key=sk,
        emit_proactive=lambda t: emitted.append(t) or True,
        now=end + timedelta(minutes=1),
    )
    assert n == 0
    assert emitted == []


def test_two_overdue_missed_both_dispatched(isolated_presence_data, monkeypatch):
    mgr = get_reminder_manager()
    sk = session_key_from_character("test")
    now = datetime(2026, 6, 8, 13, 30, 0)
    r1 = mgr.create(
        session_key=sk,
        title="一起吃早餐",
        scheduled_start=now - timedelta(hours=2),
        scheduled_end=now - timedelta(hours=1, minutes=30),
    )
    r2 = mgr.create(
        session_key=sk,
        title="一起午餐",
        scheduled_start=now - timedelta(hours=1),
        scheduled_end=now - timedelta(minutes=20),
    )

    emitted: list[str] = []

    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.is_schedule_runtime_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.build_presence_trigger",
        lambda *a, **k: "",
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.get_presence_service",
        lambda: MagicMock(),
    )

    n = run_overdue_missed_on_ready(
        session_key=sk,
        emit_proactive=lambda t: emitted.append(t) or True,
        now=now,
    )
    assert n == 2
    assert len(emitted) == 2
    assert "一起吃早餐" in emitted[0]
    assert "一起午餐" in emitted[1]
    assert mgr.get(r1.id) is None
    assert mgr.get(r2.id) is None


def test_overdue_missed_not_dispatched_twice(isolated_presence_data, monkeypatch):
    mgr = get_reminder_manager()
    sk = session_key_from_character("test")
    now = datetime(2026, 6, 8, 13, 30, 0)
    rem = mgr.create(
        session_key=sk,
        title="一起吃早餐",
        scheduled_start=now - timedelta(hours=2),
        scheduled_end=now - timedelta(hours=1, minutes=30),
    )

    emitted: list[str] = []

    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.is_schedule_runtime_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.build_presence_trigger",
        lambda *a, **k: "",
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.auto_trigger.get_presence_service",
        lambda: MagicMock(),
    )

    emit = lambda t: emitted.append(t) or True
    assert run_overdue_missed_on_ready(session_key=sk, emit_proactive=emit, now=now) == 1
    assert run_overdue_missed_on_ready(session_key=sk, emit_proactive=emit, now=now) == 0
    assert len(emitted) == 1
    assert mgr.get(rem.id) is None
