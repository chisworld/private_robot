"""分句播报：TTS 情绪标签、Live2D 表情、肢体动作的协同解析。"""

from __future__ import annotations

from pnn.pet.actions import resolve_action_name
from pnn.pet.emotion import pick_expression
from pnn.pet.reply_action import infer_action_from_text

# TTS 情绪 id → 表情名关键词（在模型可用表情里模糊匹配）
_TTS_EXPR_HINTS: dict[str, tuple[str, ...]] = {
    "angry": ("怒", "angry", "Black", "黑", "生气", "angry"),
    "asking": ("疑", "问", "asking", "?"),
    "high": ("笑", "blush", "happy", "嬉", "joy", "high", "开心"),
    "ironic": ("ironic", "讽刺", "Black", "黑脸", "ironic"),
    "soft": ("blush", "shy", "脸红", "soft", "照", "羞"),
    "normal2": ("wink", "normal", "平常"),
    "normal1": (),
}

# TTS 情绪 id → 默认肢体动作（LLM 未标注时）
_TTS_ACTION_HINTS: dict[str, str] = {
    "angry": "shake_head",
    "asking": "tilt_head",
    "high": "sway",
    "ironic": "shake_head",
    "soft": "tilt_head",
    "normal2": "nod",
}


def _default_expression(available: set[str]) -> str:
    from pnn.pet.paths import DEFAULT_EXPRESSION

    if "default" in available:
        return "default"
    if DEFAULT_EXPRESSION in available:
        return DEFAULT_EXPRESSION
    if available:
        return sorted(available)[0]
    return DEFAULT_EXPRESSION


def _llm_expr_is_neutral(expr: str, default: str) -> bool:
    """LLM 未指定具体表情（默认/neutral）时不应挡住 TTS 情绪映射。"""
    from pnn.pet.paths import DEFAULT_EXPRESSION, MODEL_NEUTRAL_EXPRESSION

    e = (expr or "").strip()
    if not e:
        return True
    if e == default:
        return True
    for neutral in (DEFAULT_EXPRESSION, MODEL_NEUTRAL_EXPRESSION):
        if e and e == neutral:
            return True
    return False


def _expression_for_tts_tag(tts_tag: str | None, available: set[str]) -> str | None:
    key = (tts_tag or "").strip().lower()
    if not key or not available:
        return None
    hints = _TTS_EXPR_HINTS.get(key, ())
    for hint in hints:
        for expr in available:
            if hint.lower() in expr.lower() or hint in expr:
                return expr
    return None


def resolve_segment_emotion_tag(
    raw_tag: str | None,
    text: str,
    char_id: str,
) -> str | None:
    """解析分句 TTS 情绪：优先 LLM 标签，否则按正文推断，最后默认。"""
    from pnn.tts.voice_library import (
        detect_tts_emotion_tag_from_text,
        load_voice_emotions,
        resolve_tts_emotion_tag,
    )

    lib = load_voice_emotions(char_id)
    if lib is None or not lib.presets:
        return None

    default = (lib.default_emotion_id or "normal1").lower()
    allowed = {str(p.get("id", "")).lower() for p in lib.presets}

    raw = (raw_tag or "").strip()
    if raw:
        resolved = resolve_tts_emotion_tag(raw, char_id)
        if resolved and resolved.lower() in allowed:
            return resolved.lower()

    inferred = detect_tts_emotion_tag_from_text(text, char_id)
    if inferred and inferred.lower() in allowed:
        return inferred.lower()

    return default if default in allowed else None


def pick_expression_for_segment(
    text: str,
    *,
    tts_tag: str | None,
    llm_expr: str | None,
    available: set[str],
) -> str:
    """为一句台词选择最贴切的 Live2D 表情。"""
    default = _default_expression(available)
    expr = (llm_expr or "").strip()

    if expr and expr in available and not _llm_expr_is_neutral(expr, default):
        return expr

    if tts_tag:
        mapped = _expression_for_tts_tag(tts_tag, available)
        if mapped:
            return mapped

    guessed = pick_expression(text, available_expressions=available, default_expr=default)
    if guessed in available and guessed != default:
        return guessed

    if expr in available:
        return expr
    return default


def pick_action_for_segment(
    text: str,
    *,
    tts_tag: str | None,
    llm_action: str | None,
    llm_expr: str | None = None,
) -> str | None:
    """为一句台词选择肢体动作：LLM 标签 > 情绪联动 > 正文推断。"""
    resolved = resolve_action_name(llm_action)
    if resolved:
        return resolved

    key = (tts_tag or "").strip().lower()
    if key in _TTS_ACTION_HINTS:
        mapped = resolve_action_name(_TTS_ACTION_HINTS[key])
        if mapped:
            return mapped

    # 兴奋/开心类表情时补 sway
    expr_low = (llm_expr or "").lower()
    if any(k in expr_low for k in ("笑", "blush", "happy", "joy")):
        return resolve_action_name("sway")

    return infer_action_from_text(text)


def build_coherence_prompt_addon(char_id: str) -> str:
    """LLM 提示：情绪标签、表情、动作三者宜一致。"""
    from pnn.tts.voice_library import load_voice_emotions

    lib = load_voice_emotions(char_id)
    if lib is None or not lib.presets:
        return (
            "【输出协同】每句句首按顺序标注（用户界面不显示）："
            "【情绪:…】【表情:…】【动作:…】（后两项可选）。"
            "开心/兴奋→ high + 笑类表情 + sway；"
            "害羞/道歉→ soft + 脸红类 + tilt_head；"
            "生气/吐槽→ angry + shake_head；疑问→ asking + tilt_head。"
        )

    ids = [str(p.get("id", "")) for p in lib.presets if p.get("id")]
    id_list = "、".join(ids)
    return (
        "【输出协同 — 情绪·表情·动作一致】\n"
        "每句完整句子句首标签顺序固定为："
        "【情绪:标签id】【表情:名称】【动作:名称】（动作可选）。\n"
        f"情绪标签 id 仅限：{id_list}。\n"
        "推荐搭配（可据语境微调）：\n"
        "- high（兴奋/开心）→ 笑/脸红类表情 → sway\n"
        "- soft（害羞/温柔/道歉）→ 脸红类表情 → tilt_head\n"
        "- angry（生气/不满）→ 黑脸/生气类表情 → shake_head\n"
        "- asking（疑问）→ 疑惑类表情 → tilt_head\n"
        "- ironic（讽刺/吐槽）→ 黑脸或默认 → shake_head\n"
        "- normal1/normal2（平常叙述）→ 默认表情；肯定用 nod，道谢/问候用 bow\n"
        "动作名称从动作列表逐字复制；不是每句都需要动作，但语气明显时应配上。"
    )
