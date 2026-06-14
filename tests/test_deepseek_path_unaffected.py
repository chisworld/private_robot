"""DeepSeek 云端路径不受本地 NSFW/lite 优化影响。"""

from __future__ import annotations

from pnn.llm.config_store import LlmConfig
from pnn.llm.local_qwen import compact_local_pet_expression_prompt
from pnn.llm.routing import should_use_local_chat
from pnn.llm.service import LlmService


def _cloud_cfg() -> LlmConfig:
    return LlmConfig(
        nsfw_enabled=False,
        api_key="sk-test-key",
        max_tokens=8192,
        max_history_messages=20,
        local_chat_lite=True,
    )


def test_cloud_route_not_local():
    cfg = _cloud_cfg()
    assert not should_use_local_chat(cfg, "你好")


def test_build_messages_cloud_keeps_full_context(monkeypatch):
    cfg = _cloud_cfg()
    monkeypatch.setattr("pnn.llm.service.load_llm_config", lambda: cfg)
    svc = LlmService()
    big_extra = "【Live2D 表情标注" + "x" * 400

    with svc._lock:
        svc.reload_from_disk()
        use_local = should_use_local_chat(svc._config, "你好")
        assert not use_local
        lite, hist_cap, max_tok = svc._resolve_local_chat_limits(svc._config, use_local)
        extra = svc._augment_extra_system_for_local(big_extra, "你好")
        msgs = svc._build_messages(
            "你好",
            [],
            extra_system=extra,
            history_cap=hist_cap,
            for_local=use_local,
            lite=lite,
        )

    assert hist_cap is None
    assert max_tok == 8192
    assert extra == big_extra
    assert lite is False

    sys_text = "\n".join(m["content"] for m in msgs if m.get("role") == "system")
    assert "程序时钟" in sys_text
    assert "本地精简模式已截断" not in sys_text

    user = msgs[-1]["content"]
    assert "[clock]" in user
    assert user.rstrip().endswith("你好")
    assert compact_local_pet_expression_prompt() not in sys_text


def test_agent_and_mcp_still_cloud_when_nsfw_on(monkeypatch):
    cfg = LlmConfig(nsfw_enabled=True, api_key="sk-test-key")

    assert not should_use_local_chat(cfg, "你好", use_agent=True)
    assert not should_use_local_chat(cfg, "搜索项目里的 foo.py")
