"""【中文】展示后处理。"""

from __future__ import annotations

from pnn.pet.chinese_display import polish_chinese_display


def test_polish_replaces_ochinchin():
    raw = "哥哥的……おちんちん……最喜欢了"
    out = polish_chinese_display(raw)
    assert "おちん" not in out
    assert "鸡鸡" in out
    assert "哥哥" in out


def test_polish_passthrough_clean_chinese():
    assert polish_chinese_display("哥哥，晚安。") == "哥哥，晚安。"
