"""TTS 称呼：日语角色勿用中文「哥哥」直读。"""

from __future__ import annotations

import pytest

from pnn.pet.reply_text import apply_address_terms_for_tts, tts_text_for_reply


@pytest.fixture
def risona_pack(monkeypatch, tmp_path):
    from pnn.characters import pack as pack_mod
    from pnn.characters.pack import CharacterPack, TimeGreetingSettings

    pack = CharacterPack(
        id="里想奈",
        name="里想奈",
        reply_language="ja",
        time_greetings=TimeGreetingSettings(
            address_zh="哥哥",
            address_ja="お兄ちゃん",
        ),
    )
    root = tmp_path / "characters" / "里想奈"
    root.mkdir(parents=True)
    (root / "pack.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(pack_mod, "CHARACTERS_ROOT", tmp_path / "characters")
    monkeypatch.setattr(
        "pnn.characters.service.character_pack_service.get_active_id",
        lambda: "里想奈",
    )
    monkeypatch.setattr(pack_mod, "load_pack", lambda cid: pack if cid == "里想奈" else None)
    monkeypatch.setattr(
        "pnn.characters.reply_lang.active_reply_language",
        lambda: "ja",
    )
    return pack


def test_apply_address_replaces_gege(risona_pack):
    out = apply_address_terms_for_tts("あら、哥哥、おかえり。", "ja")
    assert "哥哥" not in out
    assert "お兄ちゃん" in out


def test_apply_address_replaces_oniichan_cn(risona_pack):
    out = apply_address_terms_for_tts("欧尼酱又在偷懒？", "ja")
    assert "欧尼酱" not in out
    assert "お兄ちゃん" in out


def test_tts_text_for_mixed_japanese_keeps_kana(risona_pack, monkeypatch):
    monkeypatch.setattr(
        "pnn.pet.reply_text._looks_japanese",
        lambda _t: True,
    )
    out = tts_text_for_reply("こんばんは、哥哥。", "ja")
    assert "お兄ちゃん" in out
    assert "哥哥" not in out
