"""对话历史删除与日文翻译块。"""

from __future__ import annotations

import json

from pnn.memory.dialogue_history_ops import (
    remove_daily_log_turn,
    remove_turn_from_dialogue_record,
)
from pnn.memory.dialogue_zh import translate_assistant_lines_in_block
from pnn.memory.store import MemoryStore


def test_translate_assistant_lines_in_block(monkeypatch):
    from pnn.translate.service import translate_service

    monkeypatch.setattr(
        translate_service,
        "for_memory_storage",
        lambda t: "中文回复" if "ふふ" in t else t,
    )
    body = "哥哥：你好\n里想奈：ふふ、你好"
    out = translate_assistant_lines_in_block(
        body, user_label="哥哥", assistant_label="里想奈"
    )
    assert "中文回复" in out
    assert "哥哥：你好" in out


def test_remove_turn_from_dialogue_record(tmp_path, monkeypatch):
    import pnn.core.paths as paths

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", tmp_path / "memory")
    store = MemoryStore("t")
    rec = store.add(
        "哥哥：A\n里想奈：1\n\n---\n\n哥哥：B\n里想奈：2",
        kind="dialogue",
        importance=4.0,
    )
    ok = remove_turn_from_dialogue_record(
        store,
        rec.id,
        user="A",
        assistant="1",
        user_label="哥哥",
        assistant_label="里想奈",
    )
    assert ok
    updated = store._records[rec.id].content
    assert "哥哥：B" in updated
    assert "哥哥：A" not in updated


def test_remove_daily_log_turn(tmp_path):
    path = tmp_path / "log.json"
    path.write_text(
        json.dumps(
            [
                {"at": "2026-06-14T15:23:00", "user": "嗯", "assistant": "日文"},
                {"at": "2026-06-14T15:24:00", "user": "好", "assistant": "ok"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ok = remove_daily_log_turn(
        str(path),
        0,
        at="2026-06-14T15:23:00",
        user="嗯",
        assistant="日文",
    )
    assert ok
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert len(raw) == 1
    assert raw[0]["user"] == "好"
