"""记忆分类与列表 API 测试。"""

from __future__ import annotations

from pnn.memory.kinds import format_kind_stats, kind_label, memory_kind_choices
from pnn.memory.service import MemoryService


def test_kind_labels():
    assert kind_label("fact") == "事实"
    assert kind_label("event") == "事件"
    assert kind_label("dialogue") == "对话"
    choices = memory_kind_choices()
    assert choices[0] == ("", "全部分类")
    assert any(v == "event" for v, _ in choices)


def test_format_kind_stats():
    text = format_kind_stats({"fact": 3, "dialogue": 10, "event": 2})
    assert "共 15 条" in text
    assert "事实 3" in text
    assert "对话 10" in text


def test_list_memories_kind_filter(tmp_path, monkeypatch):
    import pnn.core.paths as paths

    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", mem_dir)
    monkeypatch.setattr(MemoryService, "_active_character_id", lambda self: "test")

    svc = MemoryService()
    store = svc._store("test")
    store.add("哥哥喜欢 osu", kind="fact", importance=5.0)
    store.add("昨天 osu 赌局哥哥赢了", kind="event", importance=6.0)
    store.add("哥哥：你好\n里想奈：嗯", kind="dialogue", importance=4.0)

    events = svc.list_memories(50, kind="event")
    assert len(events) == 1
    assert events[0]["kind"] == "event"
    assert events[0]["kind_label"] == "事件"

    stats = svc.memory_stats()
    assert stats["total"] == 3
    assert stats["counts"]["fact"] == 1
    assert "事实" in stats["summary"]


def test_memory_test_mode_skips_write(tmp_path, monkeypatch):
    import pnn.core.paths as paths
    from pnn.characters.pack import CharacterPack
    from pnn.memory.store import MemoryStore

    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", mem_dir)
    monkeypatch.setattr(MemoryService, "_active_character_id", lambda self: "test")

    pack = CharacterPack(id="test", name="test", test_mode=True)

    class _Svc:
        @staticmethod
        def get_active_pack():
            return pack

    monkeypatch.setattr(
        "pnn.characters.service.character_pack_service",
        _Svc(),
    )

    svc = MemoryService()
    assert svc.is_character_test_mode()
    assert not svc.is_write_enabled()
    svc.after_conversation_turn("你好", "嗯")
    store = svc._store("test")
    assert len(store._records) == 0


def test_sway_duration_and_layers():
    from pnn.pet.body_actions import build_default_sway_keyframes

    frames = build_default_sway_keyframes()
    assert frames[-1][0] >= 1500
    params = {p for _, p, _ in frames}
    assert "ParamBodyAngleX" in params
    assert "ParamAngleX" in params


def test_list_memories_fuzzy_search(tmp_path, monkeypatch):
    import pnn.core.paths as paths

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", tmp_path / "memory")
    monkeypatch.setattr(MemoryService, "_active_character_id", lambda self: "test")

    svc = MemoryService()
    store = svc._store("test")
    store.add("里想奈在 osu 赌局里输给了哥哥", kind="event", importance=6.0)

    hits = svc.list_memories(10, q="osu赌")
    assert len(hits) == 1
