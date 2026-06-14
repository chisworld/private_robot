"""本地 Qwen 上下文压缩。"""

from __future__ import annotations

from pnn.llm.config_store import LlmConfig
from pnn.llm.local_qwen import (
    compact_local_pet_expression_prompt,
    local_chat_lite_enabled,
    local_chat_max_history,
    local_chat_max_tokens,
    local_memory_max_chars,
)


def test_local_chat_defaults(monkeypatch):
    monkeypatch.delenv("LOCAL_CHAT_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LOCAL_CHAT_MAX_HISTORY", raising=False)
    monkeypatch.delenv("LOCAL_CHAT_LITE", raising=False)
    assert local_chat_max_tokens() == 1024
    assert local_chat_max_history(20) == 8
    assert local_chat_lite_enabled(None) is True


def test_local_lite_profile(monkeypatch):
    monkeypatch.delenv("LOCAL_CHAT_LITE", raising=False)
    assert local_chat_lite_enabled(True) is True
    assert local_chat_lite_enabled(False) is False
    assert local_chat_max_tokens(lite=True) == 768
    assert local_chat_max_history(20, lite=True) == 2
    assert local_memory_max_chars(lite=True) == 0


def test_local_env_overrides(monkeypatch):
    monkeypatch.setenv("LOCAL_CHAT_MAX_TOKENS", "512")
    monkeypatch.setenv("LOCAL_CHAT_MAX_HISTORY", "4")
    monkeypatch.setenv("LOCAL_MEMORY_MAX_CHARS", "500")
    monkeypatch.setenv("LOCAL_CHAT_LITE", "0")
    assert local_chat_max_tokens() == 512
    assert local_chat_max_history(20) == 4
    assert local_memory_max_chars() == 500
    assert local_chat_lite_enabled(True) is False


def test_build_messages_local_caps_memory(monkeypatch):
    from pnn.llm.service import LlmService

    cfg = LlmConfig(nsfw_enabled=True, max_history_messages=20, local_chat_lite=False)
    monkeypatch.setattr("pnn.llm.service.load_llm_config", lambda: cfg)
    monkeypatch.setenv("LOCAL_MEMORY_MAX_CHARS", "100")
    monkeypatch.setenv("LOCAL_CHAT_LITE", "0")

    svc = LlmService()
    long_mem = "记忆" * 200
    monkeypatch.setattr(svc, "_memory_context", lambda _m: long_mem)

    merged = svc._merge_extra_system("你好", None, for_local=True, lite=False)
    assert merged is not None
    assert len(merged) <= 130
    assert "截断" in merged


def test_lite_skips_memory_and_uses_compact_prompt(monkeypatch):
    from pnn.llm.service import LlmService

    cfg = LlmConfig(nsfw_enabled=True, local_chat_lite=True)
    monkeypatch.setattr("pnn.llm.service.load_llm_config", lambda: cfg)
    monkeypatch.setenv("LOCAL_CHAT_LITE", "1")

    svc = LlmService()
    monkeypatch.setattr(svc, "_memory_context", lambda _m: "不应出现的长记忆" * 50)

    merged = svc._merge_extra_system("你好", None, for_local=True, lite=True)
    assert merged is None

    extra = svc._augment_extra_system_for_local("完整表情列表" * 100, "你好")
    assert extra == compact_local_pet_expression_prompt()
    assert len(extra) < 300
