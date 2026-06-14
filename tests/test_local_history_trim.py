"""本地 lite history 截断与反套话复读。"""

from __future__ import annotations

from pnn.llm.local_qwen import (
    build_local_anti_echo_hint,
    trim_history_for_local_llm,
)
from pnn.pet.expression_tags import normalize_dialogue_quotes, strip_expression_tags


def test_trim_history_caps_assistant():
    hist = [
        {"role": "user", "content": "你好"},
        {
            "role": "assistant",
            "content": "「" + "哥哥周末阳光正好，空调也舒适，下次一定稍等一下。" * 12 + "」",
        },
        {"role": "user", "content": "今天吃什么"},
    ]
    out = trim_history_for_local_llm(hist, cap=4, lite=True)
    asst = [x for x in out if x["role"] == "assistant"][0]["content"]
    assert len(asst) <= 163
    assert asst.endswith("…")


def test_anti_echo_hint_when_long_assistant():
    hist = [{"role": "assistant", "content": "x" * 120}]
    assert "勿复读" in build_local_anti_echo_hint(hist)


def test_normalize_dialogue_quotes():
    raw = "」 「明明说过要陪哥哥的，结果呢？"
    assert "」" not in normalize_dialogue_quotes(raw)
    assert "明明说过" in normalize_dialogue_quotes(raw)


def test_strip_book_quote_monologue():
    raw = "「哥哥，现在是14点。阳光正好。」"
    out = strip_expression_tags(raw)
    assert "「" not in out
    assert "哥哥" in out
