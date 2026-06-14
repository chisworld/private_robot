"""本地 lite 模式：对话锚定，防止偏题自说自话。"""

from __future__ import annotations

from pnn.llm.config_store import LlmConfig
from pnn.llm.local_qwen import (
    build_local_lite_extra_system,
    compact_local_chat_grounding_rules,
    extract_local_preserved_extra,
)
from pnn.llm.routing import should_use_local_chat
from pnn.llm.service import LlmService


def test_local_lite_includes_grounding_and_turn_anchor(monkeypatch):
    cfg = LlmConfig(nsfw_enabled=True, api_key="sk-test", local_chat_lite=True)
    monkeypatch.setattr("pnn.llm.service.load_llm_config", lambda: cfg)
    svc = LlmService()

    with svc._lock:
        svc._config = cfg
        user_msg = "今天有点累，随便聊聊"
        use_local = should_use_local_chat(svc._config, user_msg)
        assert use_local
        lite, hist_cap, _ = svc._resolve_local_chat_limits(svc._config, use_local)
        extra = svc._augment_extra_system_for_local("ignored long prompt", user_msg)
        msgs = svc._build_messages(
            user_msg,
            [],
            extra_system=extra,
            history_cap=hist_cap,
            for_local=use_local,
            lite=lite,
        )

    sys_text = "\n".join(m["content"] for m in msgs if m.get("role") == "system")
    assert compact_local_chat_grounding_rules()[:20] in sys_text
    assert f"【本轮用户消息】「{user_msg}」" in sys_text
    assert "勿偏题" in sys_text
    assert msgs[-1]["content"] == user_msg


def test_preserve_schedule_prefix_in_lite_extra():
    big = (
        "【Live2D 表情标注 — 必须遵守】\n"
        + "- default\n" * 40
        + "\n\n[schedule] 18:00 提醒吃饭"
    )
    preserved = extract_local_preserved_extra(big)
    assert "[schedule]" in preserved
    lite_extra = build_local_lite_extra_system(big)
    assert "[schedule]" in lite_extra
    assert "Live2D 表情标注 — 必须遵守" not in lite_extra
