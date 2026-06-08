"""陪伴模式：番茄钟、今日摘要、节日、亲密度、项目搜索路由。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from pnn.agent.code_edit import looks_like_project_search_task
from pnn.agent.routing import needs_mcp_agent
from pnn.pet.presence.config import PresenceConfig
from pnn.pet.presence.daily_log import (
    append_daily_turn,
    build_daily_summary_text,
    is_daily_summary_query,
)
from pnn.pet.presence.holidays import holiday_label, normalize_birthday_md
from pnn.pet.presence.pomodoro import (
    PomodoroPhase,
    get_pomodoro_service,
    parse_pomodoro_start_minutes,
    parse_pomodoro_stop,
)
from pnn.pet.presence.service import PresenceService
from pnn.pet.presence.user_commands import handle_user_commands
from pnn.pet.reply_action import infer_action_from_text


def test_normalize_birthday_md():
    assert normalize_birthday_md("6-7") == "06-07"
    assert normalize_birthday_md("13-40") == ""
    assert normalize_birthday_md("") == ""


def test_holiday_label_birthday():
    ts = datetime(2026, 6, 7, 10, 0)
    assert holiday_label(ts, user_birthday="06-07") == "用户生日"
    ts_child = datetime(2026, 6, 1, 10, 0)
    assert holiday_label(ts_child, user_birthday="") == "儿童节"


def test_pomodoro_start_stop(isolated_presence_data, monkeypatch):
    cfg = PresenceConfig(pomodoro_enabled=True, pomodoro_work_minutes=25)
    monkeypatch.setattr(
        "pnn.pet.presence.pomodoro.load_presence_config", lambda: cfg
    )
    svc = get_pomodoro_service()
    sk = "character:test"
    assert parse_pomodoro_start_minutes("陪我专注30分钟") == 30
    assert parse_pomodoro_start_minutes("开个番茄") == 25
    assert parse_pomodoro_start_minutes("倒计时 1 小时") == 60
    assert parse_pomodoro_start_minutes("安静陪我 20min") == 20
    assert parse_pomodoro_start_minutes("进入专注模式") == 25
    assert parse_pomodoro_start_minutes("我在学习数学") is None
    assert parse_pomodoro_stop("结束专注") is True
    assert parse_pomodoro_stop("番茄先停") is True
    assert parse_pomodoro_stop("不专注了") is True
    st = svc.start(sk, 10, label="写代码")
    assert st.phase == PomodoroPhase.focus.value
    assert st.work_minutes == 10
    svc.stop(sk)
    assert svc.get_state(sk).phase == PomodoroPhase.idle.value


def test_pomodoro_tick_focus_end(isolated_presence_data, monkeypatch):
    cfg = PresenceConfig(pomodoro_break_minutes=3)
    monkeypatch.setattr(
        "pnn.pet.presence.pomodoro.load_presence_config", lambda: cfg
    )
    svc = get_pomodoro_service()
    sk = "character:tick"
    svc.start(sk, 1)
    st = svc.get_state(sk)
    st.ends_at = (datetime.now() - timedelta(seconds=1)).isoformat(timespec="seconds")
    svc._save(sk, st)
    events = svc.tick(sk)
    assert len(events) == 1
    assert events[0].kind == "focus_end"
    assert svc.get_state(sk).phase == PomodoroPhase.break_.value


def test_daily_log_and_summary_query(isolated_presence_data):
    sk = "character:log"
    assert is_daily_summary_query("今天聊了什么")
    assert is_daily_summary_query("回顾一下今天")
    assert is_daily_summary_query("刚才聊了啥")
    assert is_daily_summary_query("还记得今天说的吗")
    assert not is_daily_summary_query("今天天气怎么样")
    append_daily_turn(sk, "你好", "你好呀")
    text = build_daily_summary_text(sk)
    assert "你好" in text
    prefix = handle_user_commands("今天聊了什么", sk)
    assert "[companion]" in prefix
    assert "你好" in prefix


def test_user_command_pomodoro_prefix(isolated_presence_data, monkeypatch):
    cfg = PresenceConfig(pomodoro_enabled=True, pomodoro_work_minutes=20)
    monkeypatch.setattr(
        "pnn.pet.presence.user_commands.load_presence_config", lambda: cfg
    )
    monkeypatch.setattr(
        "pnn.pet.presence.pomodoro.load_presence_config", lambda: cfg
    )
    prefix = handle_user_commands("陪我专注", "character:pomo")
    assert "[companion]" in prefix
    assert "20" in prefix


def test_infer_action_from_text():
    assert infer_action_from_text("谢谢你啦") == "bow"
    assert infer_action_from_text("太好了！") == "jump"
    assert infer_action_from_text("不要不要") == "shake_head"


def test_project_search_routing():
    assert looks_like_project_search_task("帮我在项目里找 config 文件")
    assert looks_like_project_search_task("代码里有没有 pomodoro")
    assert looks_like_project_search_task("presence.json 在哪")
    assert looks_like_project_search_task("哪个文件定义了 PresenceService")
    assert needs_mcp_agent("帮我在项目里找 presence.json")
    assert not looks_like_project_search_task("今天聊了什么")


def test_tick_idle_skips_during_focus(isolated_presence_data, monkeypatch):
    cfg = PresenceConfig(
        presence_enabled=True,
        presence_idle_seconds=60,
        presence_idle_probability=1.0,
    )
    monkeypatch.setattr("pnn.pet.presence.service.load_presence_config", lambda: cfg)
    monkeypatch.setattr(
        "pnn.pet.presence.service.is_schedule_runtime_ready", lambda: True
    )
    monkeypatch.setattr(
        "pnn.pet.presence.service.is_proactive_ready", lambda **kw: True
    )

    class _FakePomo:
        def is_focusing(self, _sk: str) -> bool:
            return True

    monkeypatch.setattr(
        "pnn.pet.presence.pomodoro.get_pomodoro_service", lambda: _FakePomo()
    )
    svc = PresenceService("character:focus")
    svc.bind_session("character:focus")
    svc.bundle.state.last_user_activity_at = datetime.now() - timedelta(minutes=5)
    svc.wire_dispatch(emit_proactive=lambda _t: True)
    assert svc.tick_idle() is False


def test_time_greeting_once(isolated_presence_data, monkeypatch):
    cfg = PresenceConfig(presence_enabled=True, time_greeting_enabled=True)
    monkeypatch.setattr("pnn.pet.presence.service.load_presence_config", lambda: cfg)
    monkeypatch.setattr(
        "pnn.pet.presence.service.is_schedule_runtime_ready", lambda: True
    )
    svc = PresenceService("character:greet")
    svc.bind_session("character:greet")
    calls: list[str] = []
    svc.wire_dispatch(emit_proactive=lambda t: calls.append(t) or True)
    assert svc.try_time_greeting() is True
    assert svc.try_time_greeting() is False
    assert len(calls) == 1
