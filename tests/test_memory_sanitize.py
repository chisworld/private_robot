"""记忆入库清理与主动搭话跳过。"""

from __future__ import annotations

from pnn.memory.sanitize import (
    is_system_proactive_turn,
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
