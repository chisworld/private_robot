from __future__ import annotations

from datetime import datetime, timedelta

from pnn.pet.reminders.from_chat import (
    cleanup_session_reminders,
    is_valid_auto_title,
    parse_reminder_request,
    parse_user_reminder_request,
    try_create_reminder_from_assistant_reply,
    try_create_reminder_from_memory_event,
    try_create_reminder_from_text,
    try_create_reminder_from_user_message,
)
from pnn.pet.reminders.title_polish import fallback_reminder_title
from pnn.pet.reminders.manager import ReminderManager, session_key_from_character


def test_parse_remind_cook_at_time():
    now = datetime(2026, 6, 6, 17, 30, 0)
    parsed = parse_user_reminder_request("18：02提醒我该煮饭了", now=now)
    assert parsed is not None
    title, start, end = parsed
    assert title == "煮饭"
    assert start.hour == 18 and start.minute == 2
    assert (end - start).total_seconds() == 30 * 60


def test_parse_half_past_six():
    now = datetime(2026, 6, 6, 17, 0, 0)
    parsed = parse_user_reminder_request("六点半叫我煮饭", now=now)
    assert parsed is not None
    title, start, _end = parsed
    assert title == "煮饭"
    assert start.hour == 18 and start.minute == 30


def test_parse_tomorrow_lunch_together():
    now = datetime(2026, 6, 6, 18, 0, 0)
    parsed = parse_reminder_request("明天一起吃午饭吧", now=now)
    assert parsed is not None
    title, start, _end = parsed
    assert "午饭" in title
    assert start.date() == (now + timedelta(days=1)).date()
    assert start.hour == 12 and start.minute == 0


def test_parse_tomorrow_morning_wake():
    now = datetime(2026, 6, 6, 18, 57, 0)
    parsed = parse_reminder_request("明天早上叫我起床一起吃饭", now=now)
    assert parsed is not None
    title, start, _end = parsed
    assert start.date() == (now + timedelta(days=1)).date()
    assert start.hour == 7 and start.minute == 30


def test_assistant_tomorrow_commitment_same_parser(isolated_presence_data):
    sk = session_key_from_character("commit_test")
    now = datetime(2026, 6, 6, 18, 58, 0)
    reply = "那明天早上我一定准时叫你起床。"
    rem = try_create_reminder_from_text(sk, reply, now=now)
    assert rem is not None
    assert rem.scheduled_start.date() == datetime(2026, 6, 7).date()
    assert rem.scheduled_start.hour == 7
    assert rem.source == "chat"


def test_assistant_tomorrow_lunch():
    now = datetime(2026, 6, 6, 12, 0, 0)
    parsed = parse_reminder_request(
        "好啊，那明天中午我们一起吃午饭。",
        now=now,
    )
    assert parsed is not None
    title, start, _ = parsed
    assert "午饭" in title
    assert start.hour == 12


def test_parse_past_narrative_returns_none():
    assert parse_reminder_request("昨天不是说好你叫我起床一起吃饭的吗") is None


def test_parse_no_intent_returns_none():
    assert parse_user_reminder_request("今天天气不错") is None


def test_create_reminder_persists(isolated_presence_data):
    sk = session_key_from_character("里想奈")
    now = datetime(2026, 6, 6, 17, 55, 0)
    rem = try_create_reminder_from_user_message(
        sk,
        "18:02提醒我该煮饭了",
        now=now,
    )
    assert rem is not None
    assert "煮饭" in rem.title
    mgr = ReminderManager()
    mgr.reload()
    items = mgr.list_for_session(sk)
    assert len(items) == 1
    assert items[0].id == rem.id


def test_parse_tomorrow_half_past_eight_wake():
    now = datetime(2026, 6, 6, 22, 41, 0)
    parsed = parse_reminder_request("好啊，那明天你就八点半叫我起床吧", now=now)
    assert parsed is not None
    title, start, _end = parsed
    assert title == "起床"
    assert start == datetime(2026, 6, 7, 8, 30)


def test_memory_style_event_prefers_wake_title():
    now = datetime(2026, 6, 6, 22, 41, 0)
    parsed = parse_reminder_request(
        "哥哥答应明天早上九点和里想奈一起吃粽子，并让里想奈八点半叫他起床",
        now=now,
        require_intent=False,
    )
    assert parsed is not None
    title, start, _ = parsed
    assert title == "起床"
    assert start.hour == 8 and start.minute == 30


def test_parse_huangmenji_lunch_with_clock():
    now = datetime(2026, 6, 6, 23, 7, 0)
    parsed = parse_user_reminder_request(
        "明天中午12:00点我们去吃黄焖鸡米饭吧",
        now=now,
    )
    assert parsed is not None
    title, start, _ = parsed
    assert title == "黄焖鸡米饭"
    assert start == datetime(2026, 6, 7, 12, 0)


def test_specific_title_replaces_vague_lunch(isolated_presence_data):
    sk = session_key_from_character("lunch_replace")
    now = datetime(2026, 6, 6, 23, 0, 0)
    mgr = ReminderManager()
    mgr.reload()
    mgr.create(
        session_key=sk,
        title="吃饭",
        scheduled_start=datetime(2026, 6, 7, 12, 0),
        source="chat",
    )
    msg = "明天中午12:00点我们去吃黄焖鸡米饭吧"
    rem = try_create_reminder_from_user_message(
        sk,
        msg,
        now=now,
    )
    assert rem is not None
    assert "黄焖鸡米饭" in rem.title
    assert len(rem.title) >= 6
    mgr.reload()
    pending = [r for r in mgr.list_for_session(sk) if r.status.value == "pending"]
    assert len(pending) == 1
    assert "黄焖鸡米饭" in pending[0].title


def test_assistant_reply_path_disabled():
    assert (
        try_create_reminder_from_assistant_reply("character:x", "明天八点半叫你起床")
        is None
    )
    assert try_create_reminder_from_memory_event("character:x", "明天八点半叫他起床") is None


def test_invalid_dialogue_title_rejected():
    bad = "ふん、终于知道主动拜托我。不过哥哥，要是明天我敲门"
    assert not is_valid_auto_title(bad)


def test_cleanup_merges_morning_cluster(isolated_presence_data):
    sk = session_key_from_character("cleanup_test")
    now = datetime(2026, 6, 6, 20, 0, 0)
    mgr = ReminderManager()
    mgr.reload()
    base = datetime(2026, 6, 7, 7, 30)
    mgr.create(session_key=sk, title="早上", scheduled_start=base, source="chat")
    mgr.create(
        session_key=sk,
        title="起床",
        scheduled_start=datetime(2026, 6, 7, 8, 30),
        source="chat",
    )
    mgr.create(
        session_key=sk,
        title="ふん、终于知道主动拜托我。不过哥哥，要是明天我敲门的时候你还在赖床",
        scheduled_start=datetime(2026, 6, 7, 8, 30),
        source="chat",
    )
    removed = cleanup_session_reminders(sk)
    mgr.reload()
    pending = mgr.list_for_session(sk)
    assert removed >= 2
    assert len(pending) == 1
    assert pending[0].title == "起床"


def test_fallback_polish_huangmenji_with_address():
    msg = "明天中午12:00点我们去吃黄焖鸡米饭吧"
    title = fallback_reminder_title(
        "黄焖鸡米饭",
        address_zh="哥哥",
        user_text=msg,
    )
    assert title == "和哥哥约定好一起吃黄焖鸡米饭"


def test_user_message_uses_polish_title(isolated_presence_data, monkeypatch):
    def _fake_polish(
        user_text,
        raw_title,
        scheduled_start,
        *,
        character_id="",
        character_name="",
    ):
        return "和哥哥约定好一起吃黄焖鸡米饭"

    monkeypatch.setattr(
        "pnn.pet.reminders.title_polish.polish_reminder_title",
        _fake_polish,
    )
    sk = session_key_from_character("polish_test")
    now = datetime(2026, 6, 6, 23, 0, 0)
    rem = try_create_reminder_from_user_message(
        sk,
        "明天中午12:00点我们去吃黄焖鸡米饭吧",
        character_id="里想奈",
        now=now,
    )
    assert rem is not None
    assert rem.title == "和哥哥约定好一起吃黄焖鸡米饭"


def test_try_create_from_text_unified_source(isolated_presence_data):
    sk = session_key_from_character("test")
    now = datetime(2026, 6, 6, 10, 0, 0)
    rem = try_create_reminder_from_text(sk, "明天一起吃晚饭", now=now)
    assert rem is not None
    assert rem.source == "chat"
    assert rem.scheduled_start.hour == 18
    assert rem.scheduled_start.minute == 30
