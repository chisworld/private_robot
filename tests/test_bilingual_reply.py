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
    used: set[int] = set()
    assert (
        chinese_display_for_segment(raw, "こんばんは。", used_pair_indices=used)
        == "晚上好。"
    )
    assert (
        chinese_display_for_segment(raw, "おやすみ。", used_pair_indices=used)
        == "晚安。"
    )


def test_chinese_display_pairs_by_speech_content():
    raw = (
        "【情绪:soft】お兄ちゃん、突然こんな詩的なことを言うなんて……何か悩んでいることでもあるの？\n"
        "でも、もしお兄さんが世界を放浪したいのなら、私はずっとあなたについて行きます。\n"
        "どこへ行こうと、兄と一緒にいればそれで十分だった。\n"
        "【中文】哥哥，突然说这么诗意的话……是在想什么心事吗？\n"
        "不过，如果哥哥想浪迹天涯的话，我会一直跟着你的。\n"
        "不管去哪里，只要和哥哥在一起就好。"
    )
    used: set[int] = set()
    d0 = chinese_display_for_segment(
        raw,
        "お兄ちゃん、突然こんな詩的なことを言うなんて……何か悩んでいることでもあるの？",
        used_pair_indices=used,
    )
    d1 = chinese_display_for_segment(
        raw,
        "でも、もしお兄さんが世界を放浪したいのなら、私はずっとあなたについて行きます。",
        used_pair_indices=used,
    )
    d2 = chinese_display_for_segment(
        raw,
        "どこへ行こうと、兄と一緒にいればそれで十分だった。",
        used_pair_indices=used,
    )
    assert "诗意" in d0
    assert "浪迹天涯" in d1
    assert "在一起" in d2


def test_speech_gaps_skips_when_segments_already_enqueued():
    from pnn.pet.bilingual_reply import speech_gaps_from_chinese_block

    raw = (
        "【情绪:high】ふふっ、一句。\n"
        "第二句日语。\n"
        "【中文】中文一句。\n"
        "中文第二句。\n"
        "中文第三句。"
    )
    enqueued = ["ふふっ、一句。", "第二句日语。", "中文第三句。"]
    gaps = speech_gaps_from_chinese_block(raw, enqueued)
    assert gaps == []


def test_chinese_text_from_reply():
    assert chinese_text_from_reply("a\n【译文】你好") == "你好"


def test_chinese_display_full_zh_when_one_speech_many_zh_fragments():
    raw = (
        "【情绪:soft】か、かわいいだなんて……"
        "そんなこと言われても、全然嬉しくなんかないんだからね……\n"
        "【中文】说、说什么可爱……就算你这么说，我也一点都不觉得高兴哦……"
    )
    jp = (
        "か、かわいいだなんて……"
        "そんなこと言われても、全然嬉しくなんかないんだからね……"
    )
    display = chinese_display_for_segment(raw, jp, seg_index=0)
    assert "就算你这么说" in display
    assert "说什么可爱" in display
    from pnn.pet.bilingual_reply import speech_gaps_from_chinese_block

    raw = (
        "【情绪:high】ふふっ、お兄ちゃんが元気よく返事してくれると、私まで嬉しくなっちゃうよ。\n"
        "【中文】呵呵，哥哥你这么有精神地回答我，我也会变得很开心哦。\n"
        "那么，哥哥……今晚想做什么呢？\n"
        "一起玩《鸣潮》吗？"
    )
    gaps = speech_gaps_from_chinese_block(raw)
    assert len(gaps) >= 2
    assert any("今晚想做什么" in g for g in gaps)
    assert any("鸣潮" in g for g in gaps)
