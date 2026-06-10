"""记忆：时间标签与回忆式重复提取防护。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pnn.memory.config_store import MEMORY_TOP_K_MAX, clamp_top_k, load_memory_config, save_memory_config, MemoryConfig
from pnn.memory.recall_guard import is_recall_only_extraction
from pnn.memory.time_label import format_memory_line, memory_age_label


def test_memory_top_k_clamp_up_to_100(tmp_path, monkeypatch):
    import pnn.core.paths as paths

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    monkeypatch.setattr(paths, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(
        "pnn.memory.config_store.MEMORY_CONFIG_PATH",
        cfg_dir / "memory.json",
    )
    assert clamp_top_k(20) == 20
    assert clamp_top_k(100) == 100
    assert clamp_top_k(150) == MEMORY_TOP_K_MAX
    save_memory_config(MemoryConfig(top_k=80))
    assert load_memory_config().top_k == 80


def test_memory_age_label_yesterday():
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    label = memory_age_label(yesterday.isoformat())
    assert label == "昨天"


def test_format_memory_line_includes_age():
    ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    line = format_memory_line(kind="event", content="哥哥被毒蛙咬伤", created_at=ts)
    assert "昨天" in line
    assert "毒蛙" in line


def test_recall_only_when_user_says_shower_only():
    user = "我要去洗澡了"
    assistant = "哥哥要洗澡了？今天不是被毒蛙咬了吗，伤口别碰水。"
    extracted = "哥哥被毒蛙咬了，里想奈很担心"
    assert is_recall_only_extraction(user, assistant, extracted)


def test_not_recall_when_user_asks_about_frog():
    user = "昨天被毒蛙咬的伤口还疼吗"
    assistant = "让我看看…还红肿的话要去医院。"
    extracted = "哥哥昨天被毒蛙咬伤"
    assert not is_recall_only_extraction(user, assistant, extracted)


def test_expand_search_query_recall_osu():
    from pnn.memory.retrieval import expand_search_query

    q = "我昨天不是赢了你然后揉了你的胸部吗"
    expanded = expand_search_query(q, assistant_name="里想奈")
    assert "赢" in expanded
    assert "osu" in expanded or "之前" in expanded


def test_dedupe_hits_prefers_longer_dialogue():
    from pnn.memory.retrieval import dedupe_hits
    from pnn.memory.store import MemoryRecord

    short = MemoryRecord(
        id="a",
        content="哥哥：可以啊，你要是输了我就把你吃掉",
        kind="dialogue",
        importance=4.0,
        score=0.9,
        created_at="",
        updated_at="",
    )
    long = MemoryRecord(
        id="b",
        content=(
            "哥哥：可以啊，你要是输了我就把你吃掉\n"
            "里想奈：……\n"
            "哥哥：你输了\n"
            "里想奈：……\n"
            "哥哥：我要揉你的胸部"
        ),
        kind="dialogue",
        importance=4.0,
        score=0.85,
        created_at="",
        updated_at="",
    )
    out = dedupe_hits([short, long])
    assert len(out) == 1
    assert "揉" in out[0].content


def test_dialogue_exact_duplicate_skipped(tmp_path, monkeypatch):
    import pnn.core.paths as paths
    from pnn.memory.store import MemoryStore

    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", mem_dir)

    store = MemoryStore("test")
    text = "哥哥：你好\n里想奈：嗯"
    store.add(text, kind="dialogue", importance=4.0)
    assert store.has_exact_content(text, kind="dialogue")
    again = store.add(text, kind="dialogue", importance=4.0)
    assert len(store._records) == 1
    assert again.id == list(store._records.keys())[0]


def test_is_past_topic_query():
    from pnn.memory.presence_recall import is_past_topic_query

    assert is_past_topic_query("我昨天不是赢了你吗")
    assert is_past_topic_query("咱们继续玩osu吧")
    assert is_past_topic_query("那次赌约还记得吗")
    assert not is_past_topic_query("你好呀")


def test_search_presence_logs(tmp_path, monkeypatch):
    import json

    import pnn.core.paths as paths
    from pnn.memory.presence_recall import search_presence_logs

    log_dir = tmp_path / "presence" / "daily_log"
    log_dir.mkdir(parents=True)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.presence_recall._LOG_DIR", log_dir)

    day = "2026-06-09"
    path = log_dir / f"abc123_{day}.json"
    path.write_text(
        json.dumps(
            [
                {
                    "at": f"{day}T20:28:30",
                    "user": "哈哈哈，你输了，让我吃掉你",
                    "assistant": "……う、嘘でしょ！？",
                },
                {
                    "at": f"{day}T20:30:12",
                    "user": "我要揉你的胸部",
                    "assistant": "……なっ！？ ちょ、ちょっと哥哥！",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    hits = search_presence_logs("我昨天赢了你然后揉了你的胸部", days=14, max_hits=4)
    assert hits
    assert any("揉" in h.user or "揉" in h.assistant for h in hits)
    assert any("输" in h.user for h in hits)


def test_build_prompt_context_includes_presence(tmp_path, monkeypatch):
    import json

    import pnn.core.paths as paths
    from pnn.memory.config_store import MemoryConfig, save_memory_config
    from pnn.memory.service import MemoryService

    data = tmp_path / "data"
    cfg_dir = data / "config"
    mem_dir = data / "memory"
    log_dir = data / "presence" / "daily_log"
    for d in (cfg_dir, mem_dir, log_dir):
        d.mkdir(parents=True)

    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(paths, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr("pnn.memory.config_store.MEMORY_CONFIG_PATH", cfg_dir / "memory.json")
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", mem_dir)
    monkeypatch.setattr("pnn.memory.presence_recall._LOG_DIR", log_dir)
    monkeypatch.setattr(
        MemoryService,
        "_active_character_id",
        lambda self: "里想奈",
    )
    monkeypatch.setattr(
        MemoryService,
        "_dialogue_labels",
        lambda self, character_id=None: ("哥哥", "里想奈"),
    )
    monkeypatch.setattr(
        MemoryService,
        "_effective_core_card",
        lambda self, cfg: "",
    )

    save_memory_config(MemoryConfig(enabled=True, top_k=5))
    day = "2026-06-09"
    (log_dir / f"sess_{day}.json").write_text(
        json.dumps(
            [
                {
                    "at": f"{day}T20:30:12",
                    "user": "我要揉你的胸部",
                    "assistant": "……せ、せめて加減して",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    ctx = MemoryService().build_prompt_context("我昨天不是揉了你的胸部吗")
    assert "近期真实对话记录" in ctx
    assert "揉" in ctx
    assert "不得否认" in ctx or "禁止" in ctx
