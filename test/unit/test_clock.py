from __future__ import annotations

from pnn.core.clock import (
    build_time_query_system_context,
    format_clock_system_prompt,
    user_asks_current_time,
)


def test_user_asks_current_time_positive():
    assert user_asks_current_time("现在几点了")
    assert user_asks_current_time("几点钟")


def test_user_asks_current_time_negative():
    assert not user_asks_current_time("我喜欢吃红烧肉，韭菜炒蛋")
    assert not user_asks_current_time("")


def test_clock_system_prompt_forbids_unsolicited_time():
    prompt = format_clock_system_prompt()
    assert "禁止主动说出具体时刻" in prompt
    assert "spoken_ja" not in prompt
    assert "spoken_zh" not in prompt


def test_build_time_query_system_context():
    ctx = build_time_query_system_context("现在几点了")
    assert ctx is not None
    assert "【程序时钟·当前】" in ctx
    assert "【程序时钟·回答规则】" in ctx
    assert "hour=" in ctx
    assert build_time_query_system_context("我喜欢吃红烧肉") is None
