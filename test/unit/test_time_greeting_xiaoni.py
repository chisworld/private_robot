"""里想奈时段问候：哥哥 / お兄ちゃん。"""

from __future__ import annotations

from pnn.pet.time_greeting import TimeSlot, get_time_greeting


def test_xiaoni_morning_ja_uses_oniichan():
    display, tts, slot = get_time_greeting("ja", slot=TimeSlot.MORNING, char_id="里想奈")
    assert slot == TimeSlot.MORNING
    assert "哥哥" in display
    assert "主人" not in display
    assert "お兄ちゃん" in tts
    assert "ご主人" not in tts


def test_xiaoni_noon_ja():
    _display, tts, _ = get_time_greeting("ja", slot=TimeSlot.NOON, char_id="里想奈")
    assert "お兄ちゃん" in tts
    assert "ご主人様" not in tts
