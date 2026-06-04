"""情绪标签：LLM 标注解析与气泡剥离。"""

from __future__ import annotations

from pnn.pet.expression_tags import parse_tagged_piece, strip_expression_tags
from pnn.tts.voice_library import build_llm_emotion_tag_instruction, resolve_tts_emotion_tag


def test_build_emotion_instruction_for_xiaoni():
    text = build_llm_emotion_tag_instruction("里想奈")
    assert "【情绪:" in text
    assert "angry" in text
    assert "normal1" in text


def test_parse_llm_emotion_tag():
    raw = "【情绪:angry】【表情:生气】また怒ってるの？"
    expr, clean, _action, tag = parse_tagged_piece(raw, available={"生气", "default"})
    assert tag == "angry"
    assert "【情绪" not in clean
    assert resolve_tts_emotion_tag("angry", "里想奈") == "angry"


def test_strip_emotion_tag_not_in_bubble():
    raw = "【情绪:high】今日は楽しい！"
    assert "【情绪" not in strip_expression_tags(raw)
    assert "楽しい" in strip_expression_tags(raw)


def test_strip_emotion_tag_fullwidth_colon():
    raw = "【情绪：angry】また怒ってるの？"
    assert "【情绪" not in strip_expression_tags(raw)
    assert "怒って" in strip_expression_tags(raw)


def test_bubble_text_strips_emotion_only_line():
    from pnn.pet.reply_text import bubble_text_for_reply

    raw = "【情绪:happy】\n哥哥，今天天气真好。"
    out = bubble_text_for_reply(raw)
    assert "【情绪" not in out
    assert "哥哥" in out
