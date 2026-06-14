"""本地 lite 模式 prompt 压缩。"""

from __future__ import annotations

from pnn.llm.config_store import LlmConfig
from pnn.llm.service import llm_service
from pnn.llm.local_qwen import estimate_prompt_chars


def test_local_lite_skips_clock_prefix(monkeypatch):
    cfg = LlmConfig(nsfw_enabled=True, api_key="sk-test", local_chat_lite=True)
    monkeypatch.setattr("pnn.llm.service.load_llm_config", lambda: cfg)
    with llm_service._lock:
        llm_service._config = cfg
        lite, hist_cap, _ = llm_service._resolve_local_chat_limits(
            llm_service._config, True
        )
        extra = llm_service._augment_extra_system_for_local("ignored", "你好")
        msgs = llm_service._build_messages(
            "你好",
            [],
            extra_system=extra,
            history_cap=hist_cap,
            for_local=True,
            lite=lite,
        )
    assert estimate_prompt_chars(msgs) < 2800
    user = msgs[-1]["content"]
    assert user == "你好"
    assert "[clock]" not in user
    sys_text = "\n".join(m["content"] for m in msgs if m.get("role") == "system")
    assert "对话锚定" in sys_text
    assert "【本轮用户消息】「你好」" in sys_text
