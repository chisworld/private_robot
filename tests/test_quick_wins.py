"""Quick wins: translate cache keys, MemoryStore instance cache."""

from __future__ import annotations

from pnn.memory.service import memory_service
from pnn.translate import service as translate_module
from pnn.translate.config_store import TranslateConfig
from pnn.translate.service import _cache_key, _cache_put, translate_service


def test_translate_peek_hits_after_store(monkeypatch) -> None:
    translate_module._CACHE.clear()
    cfg = TranslateConfig(provider="bing", from_lang="ja", to_lang="zh", enabled=True)

    monkeypatch.setattr(
        "pnn.translate.service.load_translate_config",
        lambda: cfg,
    )
    monkeypatch.setattr(
        translate_service,
        "display_translation_for_bubble",
        lambda: True,
    )
    monkeypatch.setattr(translate_service, "looks_japanese", lambda _text: True)
    monkeypatch.setattr(
        translate_service,
        "looks_chinese",
        lambda _text: False,
    )

    raw = "こんにちは"
    _cache_put([_cache_key(cfg, raw)], "你好")

    assert translate_service.peek_bubble_translation(raw) == "你好"


def test_memory_store_instance_cached(monkeypatch) -> None:
    monkeypatch.setattr(memory_service, "_active_character_id", lambda: "test_char")
    memory_service._stores.clear()

    first = memory_service._store()
    second = memory_service._store()
    assert first is second

    third = memory_service._store("other_char")
    assert third is not first
