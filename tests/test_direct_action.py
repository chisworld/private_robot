"""direct_action 用户口令解析。"""

from __future__ import annotations

from pnn.pet.direct_action import (
    build_direct_action_prompt,
    parse_direct_action_command,
)


def test_jump_commands_disabled():
    assert parse_direct_action_command("跳") is None
    assert parse_direct_action_command("跳一下") is None
    assert parse_direct_action_command("跳起来") is None
    assert parse_direct_action_command("里想奈你跳一下") is None


def test_sit_commands():
    assert parse_direct_action_command("坐") == "sit"
    assert parse_direct_action_command("坐下") == "sit"
    assert parse_direct_action_command("坐一下") == "sit"
    assert parse_direct_action_command("那就坐吧") == "sit"
    assert parse_direct_action_command("请坐") == "sit"


def test_rejects_negation_and_questions():
    assert parse_direct_action_command("不要跳") is None
    assert parse_direct_action_command("别坐") is None
    assert parse_direct_action_command("你能跳吗") is None
    assert parse_direct_action_command("为什么跳") is None


def test_rejects_long_chat():
    assert parse_direct_action_command("今天天气不错我们聊聊") is None


def test_direct_action_prompt():
    prompt = build_direct_action_prompt("sit")
    assert "坐" in prompt
    assert "direct_action" in prompt
