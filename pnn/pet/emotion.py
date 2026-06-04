"""根据回复文本选择 Live2D 表情（关键词匹配，不依赖模型特定名称）。"""

from __future__ import annotations

_EMOTION_KEYWORDS: dict[str, list[str]] = {
    "happy": ["笑", "嘻", "开心", "喜", "happy", "smile"],
    "love": ["爱心", "爱", "love", "heart", "心", "比心"],
    "angry": ["生气", "怒", "angry", "mad"],
    "sad": ["眼泪", "泪", "sad", "cry", "泣", "悲", "流泪"],
    "shy": ["脸红", "羞", "shy", "blush", "照"],
    "confused": ["晕", "疑惑", "confused", "dizzy", "困"],
    "surprise": ["惊", "surprise", "shock", "震"],
}


def detect_emotion(text: str) -> str:
    t = text.lower()
    if any(
        k in t
        for k in (
            "かわいい",
            "好き",
            "大好き",
            "愛",
            "嬉しい",
            "楽しい",
            "素敵",
            "最高",
            "笑",
            "ありがとう",
            "よかった",
        )
    ):
        return "happy"
    if any(k in t for k in ("愛して", "大好き", "キス", "抱き")):
        return "love"
    if any(k in t for k in ("怒", "ふざけ", "ばか", "最低", "許", "むかつく")):
        return "angry"
    if any(k in t for k in ("悲", "泣", "ごめん", "つらい", "寂しい", "さようなら", "別れ")):
        return "sad"
    if any(k in t for k in ("恥ずかしい", "照れ", "はじ", "どきどき", "胸", "ドキドキ")):
        return "shy"
    if any(k in t for k in ("えっ", "なに", "なぜ", "どうして", "混乱", "わからない", "不思議")):
        return "confused"
    if any(k in t for k in ("まさか", "嘘", "本当", "驚", "びっくり")):
        return "surprise"
    return "default"


def pick_expression(
    text: str,
    *,
    available_expressions: set[str] | None = None,
    default_expr: str = "default",
) -> str:
    """Resolve emotion key to the best-matching expression in the available set."""
    key = detect_emotion(text)
    available = available_expressions or set()

    if available and key in _EMOTION_KEYWORDS:
        for keyword in _EMOTION_KEYWORDS[key]:
            for expr in available:
                if keyword in expr:
                    return expr

    if default_expr and default_expr in available:
        return default_expr
    if available:
        return next(iter(available), "default")
    return default_expr or key
