"""本地模型省略标签 → 标准【情绪/表情:…】格式。"""

from __future__ import annotations

from pnn.pet.expression_tags import (
    normalize_pet_output_tags,
    parse_tagged_piece,
    strip_expression_tags,
)


def test_bare_colon_emotion_tag():
    raw = "【:soft】你好呀。"
    out = normalize_pet_output_tags(raw)
    assert out.startswith("【情绪:soft】")


def test_bare_colon_expression_tag():
    avail = {"skirt_side", "default", "Black"}
    raw = "【:skirt_side】【动作:stretch】"
    out = normalize_pet_output_tags(raw, available=avail)
    assert "【表情:skirt_side】" in out
    assert "【动作:stretch】" in out


def test_parse_after_normalize():
    avail = {"skirt_side", "default"}
    piece = normalize_pet_output_tags(
        "【:normal2】【:skirt_side】看着你的脸。",
        available=avail,
    )
    expr, clean, action, emo = parse_tagged_piece(piece, available=avail)
    assert emo == "normal2"
    assert expr == "skirt_side"
    assert "看着你的脸" in clean


def test_combined_colon_tag_from_local_qwen():
    avail = {"default", "Black", "skirt_side"}
    raw = "【high:default:default】 测试成功。"
    out = normalize_pet_output_tags(raw, available=avail)
    assert "【情绪:high】" in out
    assert "【表情:default】" in out
    assert strip_expression_tags(out) == "测试成功。"


def test_strip_removes_normalized_tags():
    raw = normalize_pet_output_tags("【:soft】正文。", available=set())
    assert strip_expression_tags(raw) == "正文。"


def test_strip_unclosed_paren_narration():
    raw = (
        "【情绪:normal1】（坐在沙发上，手里还拿着游戏手柄，听到你的话后，"
        "微微抬起头，那双深邃的眼眸平静地注视着你，嘴角勾起一抹似有若无的弧度。"
    )
    assert strip_expression_tags(raw) == ""


def test_strip_paren_keeps_dialogue():
    raw = "【:soft】（嗯？）你好呀，哥哥。"
    out = strip_expression_tags(normalize_pet_output_tags(raw, available=set()))
    assert "你好呀" in out
    assert "坐在" not in out


def test_parse_skips_narration_only_sentence():
    avail = {"default"}
    piece = "【情绪:normal1】（坐在沙发上，手里还拿着游戏手柄，听到你的话后，微微抬起头。"
    expr, clean, action, emo = parse_tagged_piece(piece, available=avail)
    assert emo == "normal1"
    assert clean == ""
