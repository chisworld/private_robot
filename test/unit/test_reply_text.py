from pnn.pet.reply_text import (
    bubble_text_for_reply,
    strip_memory_recall_phrases,
    tts_text_for_reply,
)


def test_strip_memory_recall_zh():
    assert strip_memory_recall_phrases("根据长期记忆，你的妹妹叫小樱。") == "你的妹妹叫小樱。"
    assert strip_memory_recall_phrases("我想起啦，你最喜欢可乐。") == "你最喜欢可乐。"
    assert strip_memory_recall_phrases("【长期记忆】主人喜欢猫") == "主人喜欢猫"


def test_strip_memory_recall_ja():
    assert strip_memory_recall_phrases("思い出しました、妹の名前はサクラです。") == "妹の名前はサクラです。"
    assert strip_memory_recall_phrases("記憶によると、ご主人様は猫が好きです。") == "ご主人様は猫が好きです。"


def test_strip_memory_meta_whole_sentence():
    raw = (
        "唔…塞拉想想看！好像是前几天主人提到的吧？"
        "塞拉的记忆里都有好好记着呢！主人是不是觉得塞拉记性不好呀？嘿嘿~"
    )
    out = strip_memory_recall_phrases(raw)
    assert "记忆" not in out
    assert "记性" not in out
    assert "前几天" in out
    assert "想想看" in out


def test_strip_memory_admin_summary():
    summary = "主人询问塞拉是否记得妹妹的名字，塞拉记得妹妹叫里想奈，并提到是前几天主人告诉她的"
    assert strip_memory_recall_phrases(summary) == ""


def test_bubble_text_for_reply():
    assert bubble_text_for_reply("  我想起，你好呀  ") == "你好呀"


def test_tts_text_for_reply_ja_passthrough():
    assert tts_text_for_reply("こんにちは、ご主人様。", "ja") == "こんにちは、ご主人様。"
