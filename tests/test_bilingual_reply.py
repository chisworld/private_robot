"""双语回复解析与分流。"""

from __future__ import annotations

from pnn.pet.bilingual_reply import (
    chinese_display_for_segment,
    chinese_text_from_reply,
    speech_buffer_for_tts,
    split_bilingual_reply,
)
from pnn.pet.reply_text import (
    bubble_text_for_reply,
    memory_text_for_reply,
    terminal_text_for_reply,
    tts_text_for_reply,
)


def test_split_bilingual_reply():
    raw = "【情绪:soft】こんばんは、お兄ちゃん。\n【中文】晚上好，哥哥。"
    bi = split_bilingual_reply(raw)
    assert bi.has_chinese_block
    assert "こんばんは" in bi.speech
    assert bi.chinese == "晚上好，哥哥。"


def test_speech_buffer_strips_chinese_block():
    raw = "こんにちは。\n【中文】你好。"
    assert speech_buffer_for_tts(raw) == "こんにちは。"


def test_bubble_uses_chinese_block(monkeypatch):
    monkeypatch.setattr(
        "pnn.characters.reply_lang.active_reply_language",
        lambda: "ja",
    )
    raw = "【表情:default】おやすみ。\n【中文】晚安。"
    assert bubble_text_for_reply(raw) == "晚安。"
    assert terminal_text_for_reply(raw) == "晚安。"


def test_tts_uses_speech_only(monkeypatch):
    monkeypatch.setattr(
        "pnn.characters.reply_lang.active_reply_language",
        lambda: "ja",
    )
    raw = "おやすみなさい。\n【中文】晚安。"
    assert tts_text_for_reply(raw, "ja") == "おやすみなさい。"


def test_memory_uses_chinese_block():
    raw = "さようなら。\n【中文】再见。"
    assert memory_text_for_reply(raw) == "再见。"


def test_bubble_hides_japanese_during_stream_before_marker(monkeypatch):
    monkeypatch.setattr(
        "pnn.characters.reply_lang.active_reply_language",
        lambda: "ja",
    )
    monkeypatch.setattr(
        "pnn.pet.bilingual_reply.bilingual_reply_enabled",
        lambda: True,
    )
    # 已出现【中文】标记但内容未到时：不展示
    assert bubble_text_for_reply("こんばんは。\n【中文】") == ""


def test_bubble_fallback_translate_without_chinese_block(monkeypatch):
    class _FakeTranslate:
        @staticmethod
        def display_translation_for_bubble():
            return True

        @staticmethod
        def peek_bubble_translation(_text):
            return None

        @staticmethod
        def to_display_chinese(_text):
            return "晚上好。"

        @staticmethod
        def looks_chinese(_text):
            return False

    monkeypatch.setattr(
        "pnn.characters.reply_lang.active_reply_language",
        lambda: "ja",
    )
    monkeypatch.setattr(
        "pnn.translate.service.translate_service",
        _FakeTranslate(),
    )
    assert bubble_text_for_reply("こんばんは。") == "晚上好。"


def test_chinese_display_for_segment_by_index():
    raw = (
        "【情绪:soft】こんばんは。\n"
        "おやすみ。\n"
        "【中文】晚上好。\n"
        "晚安。"
    )
    assert chinese_display_for_segment(raw, "こんばんは。", seg_index=0) == "晚上好。"
    assert chinese_display_for_segment(raw, "おやすみ。", seg_index=1) == "晚安。"


def test_chinese_text_from_reply():
    assert chinese_text_from_reply("a\n【译文】你好") == "你好"
