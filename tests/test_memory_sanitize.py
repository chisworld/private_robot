"""记忆入库清理与主动搭话跳过。"""

from __future__ import annotations

from pnn.memory.sanitize import (
    is_schedule_proactive_context,
    is_system_proactive_turn,
    proactive_memory_user_line,
    strip_expression_tags,
)


def test_strip_emotion_and_action_tags():
    raw = "【情绪:normal1】【动作:tilt_head】真是的…哥哥"
    cleaned = strip_expression_tags(raw)
    assert "【情绪" not in cleaned
    assert "【动作" not in cleaned
    assert "真是的" in cleaned


def test_is_system_proactive_turn():
    assert is_system_proactive_turn("（请根据系统背景主动开口，不要复述系统文本）")
    assert not is_system_proactive_turn("哥哥你好")


def test_memory_skips_proactive_turn(monkeypatch):
    from pnn.memory.service import memory_service

    add_calls: list = []

    class FakeStore:
        def get_state(self):
            return {}

        def save_state(self, _state) -> None:
            pass

        def add(self, *args, **kwargs):
            add_calls.append(args)

    cfg = type(
        "C",
        (),
        {"enabled": True, "extraction_enabled": False, "diary_enabled": False},
    )()

    monkeypatch.setattr(memory_service, "_store", lambda: FakeStore())
    monkeypatch.setattr("pnn.memory.service.load_memory_config", lambda: cfg)
    monkeypatch.setattr(memory_service, "_buffer_turn", lambda *a, **k: None)

    memory_service.after_conversation_turn(
        "（请根据系统背景主动开口，不要复述系统文本）",
        "【情绪:normal1】你好",
        [],
    )
    assert add_calls == []


def test_memory_dialogue_strips_tags(monkeypatch):
    from pnn.memory.service import memory_service

    add_calls: list = []

    class FakeStore:
        def get_state(self):
            return {}

        def save_state(self, _state) -> None:
            pass

        def add(self, block, **kwargs):
            add_calls.append(block)

    cfg = type(
        "C",
        (),
        {"enabled": True, "extraction_enabled": False, "diary_enabled": False},
    )()

    monkeypatch.setattr(memory_service, "_store", lambda: FakeStore())
    monkeypatch.setattr("pnn.memory.service.load_memory_config", lambda: cfg)
    monkeypatch.setattr(memory_service, "_buffer_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory_service, "_dialogue_labels", lambda: ("哥哥", "里想奈"))

    memory_service.after_conversation_turn(
        "在吗",
        "【情绪:normal1】【动作:tilt_head】真是的…",
        [],
    )
    assert len(add_calls) == 1
    assert "【情绪" not in add_calls[0]
    assert "【动作" not in add_calls[0]
    assert "真是的" in add_calls[0]


def test_proactive_memory_user_line_from_reminder_context():
    ctx = (
        "[schedule-reminder · 仅供角色反应，勿当作用户原话]\n"
        "约定「鸣潮」的时间到了（2026-06-07 21:07 至 21:37）。"
    )
    line = proactive_memory_user_line(ctx)
    assert line.startswith("日程提醒")
    assert "鸣潮" in line
    assert "空闲搭话" not in line


def test_absence_return_with_timeline_is_not_schedule():
    ctx = (
        "[系统提醒 · 仅供角色反应，勿当作用户原话]\n"
        "当前无进行中的日程待办；勿编造用户忘记或爽约某约定。\n"
        "近期事件时间线：\n"
        "- 06-07 20:00 约定「鸣潮」已提醒\n"
        "用户重新打开会话。"
    )
    assert not is_schedule_proactive_context(ctx)
    line = proactive_memory_user_line(ctx)
    assert line.startswith("空闲搭话")


def test_is_idle_proactive_memory_user_line():
    from pnn.memory.sanitize import is_idle_proactive_memory_user_line

    assert is_idle_proactive_memory_user_line("空闲搭话·当前无进行中的日程待办")
    assert is_idle_proactive_memory_user_line("空闲对话·时段问候")
    assert not is_idle_proactive_memory_user_line("日程提醒·约定「煮饭」的时间到了")
    assert not is_idle_proactive_memory_user_line("哥哥你好")


def test_after_proactive_turn_skips_idle_dialogue(monkeypatch):
    from pnn.memory.service import memory_service

    add_calls: list = []

    class FakeStore:
        def get_state(self):
            return {}

        def save_state(self, _state) -> None:
            pass

        def add(self, block, **kwargs):
            add_calls.append(block)

    cfg = type(
        "C",
        (),
        {"enabled": True, "extraction_enabled": True, "diary_enabled": False},
    )()

    monkeypatch.setattr(memory_service, "_store", lambda: FakeStore())
    monkeypatch.setattr("pnn.memory.service.load_memory_config", lambda: cfg)
    monkeypatch.setattr(memory_service, "_buffer_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory_service, "_dialogue_labels", lambda: ("哥哥", "里想奈"))
    monkeypatch.setattr(memory_service, "extract_turn_events", lambda *a, **k: {"save": True})

    memory_service.after_proactive_turn(
        "约定「煮饭」的时间到了",
        "哥哥，该去煮饭了哦",
        [],
    )
    assert add_calls == []


def test_after_proactive_turn_writes_schedule_dialogue(monkeypatch):
    from pnn.memory.service import memory_service

    add_calls: list = []

    class FakeStore:
        def get_state(self):
            return {}

        def save_state(self, _state) -> None:
            pass

        def add(self, block, **kwargs):
            add_calls.append(block)

    cfg = type(
        "C",
        (),
        {"enabled": True, "extraction_enabled": True, "diary_enabled": False},
    )()

    monkeypatch.setattr(memory_service, "_store", lambda: FakeStore())
    monkeypatch.setattr("pnn.memory.service.load_memory_config", lambda: cfg)
    monkeypatch.setattr(memory_service, "_buffer_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory_service, "_dialogue_labels", lambda: ("哥哥", "里想奈"))
    monkeypatch.setattr(memory_service, "extract_turn_events", lambda *a, **k: {"save": True})

    ctx = (
        "[schedule-reminder · 仅供角色反应，勿当作用户原话]\n"
        "约定「煮饭」的时间到了（2026-06-07 21:07 至 21:37）。"
    )
    memory_service.after_proactive_turn(ctx, "哥哥，该去煮饭了哦", [])
    assert len(add_calls) == 1
    assert "日程提醒" in add_calls[0]
    assert "该去煮饭" in add_calls[0]


def test_after_idle_assistant_turn_skips_dialogue(monkeypatch):
    from pnn.memory.service import memory_service

    add_calls: list = []

    class FakeStore:
        def get_state(self):
            return {}

        def save_state(self, _state) -> None:
            pass

        def add(self, block, **kwargs):
            add_calls.append(block)

    cfg = type(
        "C",
        (),
        {"enabled": True, "extraction_enabled": True, "diary_enabled": False},
    )()

    monkeypatch.setattr(memory_service, "_store", lambda: FakeStore())
    monkeypatch.setattr("pnn.memory.service.load_memory_config", lambda: cfg)
    monkeypatch.setattr(memory_service, "_buffer_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory_service, "_dialogue_labels", lambda: ("哥哥", "里想奈"))

    memory_service.after_idle_assistant_turn("早上好，哥哥", trigger="时段问候")
    assert add_calls == []


def test_memory_record_date_prefers_created_at():
    from pnn.memory.time_label import memory_record_date

    day = memory_record_date(
        "2026-06-09T22:00:00+08:00",
        "2026-06-10T18:00:00+08:00",
    )
    assert day == "2026-06-09"
