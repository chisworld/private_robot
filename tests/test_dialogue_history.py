"""对话历史合并与排序测试。"""

from __future__ import annotations

import json

from pnn.memory.dialogue_history import load_dialogue_history


def test_dialogue_history_sorted_and_merged(tmp_path, monkeypatch):
    import pnn.core.paths as paths
    from pnn.memory.store import MemoryStore

    mem_dir = tmp_path / "memory"
    log_dir = tmp_path / "presence" / "daily_log"
    log_dir.mkdir(parents=True)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", mem_dir)
    monkeypatch.setattr("pnn.memory.presence_recall._LOG_DIR", log_dir)
    monkeypatch.setattr("pnn.memory.presence_recall._list_recent_log_files", lambda days=60: [])

    store = MemoryStore("test")
    store.add(
        "哥哥：第二句\n里想奈：嗯嗯",
        kind="dialogue",
        importance=4.0,
    )
    store.add(
        "哥哥：第一句\n里想奈：你好",
        kind="dialogue",
        importance=4.0,
    )

    items = load_dialogue_history(
        store=store,
        user_label="哥哥",
        assistant_label="里想奈",
        days=30,
        limit=50,
    )
    assert len(items) == 2
    assert items[0]["user"] in ("第二句", "第一句")
    assert "display_time" in items[0]


def test_dialogue_history_includes_presence(tmp_path, monkeypatch):
    import pnn.core.paths as paths
    from pnn.memory.store import MemoryStore

    mem_dir = tmp_path / "memory"
    log_dir = tmp_path / "presence" / "daily_log"
    log_dir.mkdir(parents=True)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", mem_dir)
    monkeypatch.setattr("pnn.memory.presence_recall._LOG_DIR", log_dir)

    day = "2026-06-09"
    (log_dir / f"abc_{day}.json").write_text(
        json.dumps(
            [
                {
                    "at": f"{day}T20:30:12",
                    "user": "我要揉你的胸部",
                    "assistant": "……哥哥！",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = MemoryStore("test")
    items = load_dialogue_history(
        store=store,
        user_label="哥哥",
        assistant_label="里想奈",
        days=30,
        limit=50,
    )
    assert len(items) == 1
    assert items[0]["source"] == "presence"
    assert "揉" in items[0]["user"]
