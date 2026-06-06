"""时段问候：pack.json time_greetings 配置驱动。"""

from __future__ import annotations

from pnn.characters.pack import TimeGreetingSettings
from pnn.pet.time_greeting import TimeSlot, get_time_greeting


def test_pack_time_greeting_settings_from_dict():
    raw = {
        "address_zh": "哥哥",
        "address_ja": "お兄ちゃん",
        "slots": {
            "morning": {
                "display": "早安",
                "zh": "早安哥哥",
                "ja": "おはよう",
            }
        },
    }
    settings = TimeGreetingSettings.from_dict(raw)
    assert settings.address_zh == "哥哥"
    assert settings.address_ja == "お兄ちゃん"
    assert settings.slots["morning"].display == "早安"


def test_risona_uses_pack_address():
    display, tts, slot = get_time_greeting("ja", slot=TimeSlot.MORNING, char_id="里想奈")
    assert slot == TimeSlot.MORNING
    assert "哥哥" in display
    assert "主人" not in display
    assert "お兄ちゃん" in tts
    assert "ご主人" not in tts


def test_risona_noon_ja():
    _display, tts, _ = get_time_greeting("ja", slot=TimeSlot.NOON, char_id="里想奈")
    assert "お兄ちゃん" in tts
    assert "ご主人様" not in tts


def test_sera_default_master_address():
    display, tts, _ = get_time_greeting("ja", slot=TimeSlot.EVENING, char_id="塞拉")
    assert "主人" in display
    assert "ご主人様" in tts


def test_slot_override_beats_address(monkeypatch, tmp_path):
    from pnn.characters import pack as pack_mod

    char_dir = tmp_path / "测试角色"
    char_dir.mkdir()
    (char_dir / "pack.json").write_text(
        """{
  "id": "测试角色",
  "time_greetings": {
    "address_zh": "哥哥",
    "slots": {
      "morning": {
        "display": "自定义早安",
        "zh": "自定义早安",
        "ja": "カスタムおはよう"
      }
    }
  }
}""",
        encoding="utf-8",
    )
    monkeypatch.setattr(pack_mod, "CHARACTERS_ROOT", tmp_path)
    display, tts, slot = get_time_greeting("ja", slot=TimeSlot.MORNING, char_id="测试角色")
    assert slot == TimeSlot.MORNING
    assert display == "自定义早安"
    assert tts == "カスタムおはよう"
