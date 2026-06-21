"""speech_sync 分句协同解析。"""

from __future__ import annotations

from pnn.pet.speech_sync import (
    _default_expression,
    pick_action_for_segment,
    pick_expression_for_segment,
    resolve_segment_emotion_tag,
)


def test_infer_emotion_from_text_when_no_llm_tag():
    tag = resolve_segment_emotion_tag("", "太好了！好开心啊！", "里想奈")
    assert tag == "high"


def test_pick_expression_uses_tts_tag_when_llm_default():
    available = {"里想奈", "blush", "Black", "default"}
    expr = pick_expression_for_segment(
        "……对不起啦",
        tts_tag="soft",
        llm_expr=_default_expression(available),
        available=available,
    )
    assert expr == "blush"


def test_pick_expression_uses_tts_tag_when_llm_model_default():
    from pnn.pet.paths import DEFAULT_EXPRESSION

    available = {"blush", "Black", "default"}
    expr = pick_expression_for_segment(
        "……对不起啦",
        tts_tag="soft",
        llm_expr=DEFAULT_EXPRESSION,
        available=available,
    )
    assert expr == "blush"


def test_pick_action_from_emotion_tag():
    action = pick_action_for_segment(
        "随便说说",
        tts_tag="high",
        llm_action=None,
    )
    assert action == "sway"


def test_pick_action_prefers_llm_tag():
    action = pick_action_for_segment(
        "谢谢哥哥",
        tts_tag="high",
        llm_action="bow",
    )
    assert action == "bow"


def test_user_requested_emotion_overrides_asking_inference():
    tag = resolve_segment_emotion_tag(
        "asking",
        "这样可以吗？有点害羞……",
        "里想奈",
        user_msg="你发出well-behaved的情绪声音听听",
    )
    assert tag == "well-behaved"
