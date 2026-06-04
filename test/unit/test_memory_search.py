from pnn.memory.retrieval import active_assistant_label, expand_search_query, is_negative_memory
from pnn.memory.store import MemoryRecord, MemoryStore, _relevance_score


def test_expand_uses_passed_assistant_name():
    q = expand_search_query("你妹妹叫什么", assistant_name="小缘")
    assert "小缘" in q
    assert "小缘的妹妹" in q
    assert "塞拉" not in q


def test_expand_different_characters_independent():
    a = expand_search_query("你姐姐呢", assistant_name="角色A")
    b = expand_search_query("你姐姐呢", assistant_name="角色B")
    assert "角色A的姐姐" in a
    assert "角色B的姐姐" in b
    assert "角色A" not in b


def test_expand_no_hardcoded_npc_name():
    q = expand_search_query("你妹妹叫什么", assistant_name="测试角色")
    assert "里想奈" not in q


def test_is_negative_memory():
    assert is_negative_memory("助手表示没有相关记忆，感到困惑")
    assert not is_negative_memory("测试角色的妹妹叫某某")


def test_relevance_uses_dynamic_assistant_name():
    fact = MemoryRecord(id="1", content="小缘的妹妹叫花子", kind="fact", importance=8.0)
    wrong = MemoryRecord(id="2", content="主人的妹妹叫花子", kind="fact", importance=5.0)
    q = "你妹妹叫什么"
    assert _relevance_score(q, fact, assistant_name="小缘") > _relevance_score(
        q, wrong, assistant_name="小缘"
    )


def test_relevance_prefers_sister_fact_over_unrelated(tmp_path, monkeypatch):
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.store._chroma_available", lambda: False)

    store = MemoryStore("test_char")
    store.add("主人最近在玩某款游戏", kind="fact", importance=5.0)
    store.add("测试酱的妹妹叫花子", kind="fact", importance=8.0)
    store.add(
        "主人提到测试酱有妹妹，但测试酱对此没有记忆，感到困惑",
        kind="event",
        importance=5.0,
    )

    hits = store.search("你妹妹叫什么", top_k=3, assistant_name="测试酱")
    assert hits
    assert "花子" in hits[0].content
    assert "游戏" not in hits[0].content


def test_purge_negative_memories(tmp_path, monkeypatch):
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.store._chroma_available", lambda: False)

    store = MemoryStore("test_char")
    store._records["bad"] = MemoryRecord(
        id="bad", content="助手表示没有相关记忆", kind="chat", importance=3.0
    )
    store._records["good"] = MemoryRecord(
        id="good", content="某角色的妹妹叫花子", kind="fact", importance=8.0
    )
    store._save_index()
    n = store.purge_negative_memories()
    assert n == 1
    assert len(store.list_all()) == 1


def test_add_rejects_negative_memory(tmp_path, monkeypatch):
    monkeypatch.setattr("pnn.memory.store.MEMORY_DATA_DIR", tmp_path)
    monkeypatch.setattr("pnn.memory.store._chroma_available", lambda: False)
    store = MemoryStore("test_char")
    try:
        store.add("助手表示没有相关记忆", kind="chat")
        raise AssertionError("should raise ValueError")
    except ValueError:
        pass
