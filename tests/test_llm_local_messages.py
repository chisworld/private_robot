"""本地 llama-server 消息格式（Qwen system 合并）。"""

from __future__ import annotations

from pnn.llm.client import coalesce_messages_for_local_llm


def test_coalesce_multiple_leading_system_into_one():
    raw = [
        {"role": "system", "content": "时钟"},
        {"role": "system", "content": "角色设定"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "嗨"},
        {"role": "user", "content": "再问一句"},
    ]
    out = coalesce_messages_for_local_llm(raw)
    assert len(out) == 4
    assert out[0]["role"] == "system"
    assert "时钟" in out[0]["content"] and "角色设定" in out[0]["content"]
    assert out[1]["role"] == "user"


def test_late_system_becomes_user_hint():
    raw = [
        {"role": "system", "content": "规则"},
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "system", "content": "迟到注入"},
        {"role": "user", "content": "c"},
    ]
    out = coalesce_messages_for_local_llm(raw)
    assert out[0]["role"] == "system"
    assert out[-2]["role"] == "user"
    assert "迟到注入" in out[-2]["content"]


def test_coalesce_idempotent():
    raw = [
        {"role": "system", "content": "a"},
        {"role": "system", "content": "b"},
        {"role": "user", "content": "hi"},
    ]
    once = coalesce_messages_for_local_llm(raw)
    twice = coalesce_messages_for_local_llm(once)
    assert once == twice


def test_local_payload_disables_qwen_thinking():
    from pnn.llm.client import DeepSeekClient

    client = DeepSeekClient(
        api_key="local",
        base_url="http://127.0.0.1:8080",
        model="qwen3.6",
    )
    payload = client._build_payload(
        [{"role": "user", "content": "hi"}],
        temperature=0.7,
        max_tokens=32,
        stream=True,
        thinking_enabled=False,
        reasoning_effort="high",
    )
    assert payload.get("chat_template_kwargs") == {"enable_thinking": False}
