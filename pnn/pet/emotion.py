"""根据回复文本选择 Live2D 表情（与 apps/web pet 页一致）。"""

from __future__ import annotations

EMOTION_MAP: dict[str, str] = {
    "happy": "笑嘻",
    "love": "组合2 爱心",
    "angry": "组合1 生气",
    "sad": "眼泪1",
    "shy": "脸红",
    "confused": "组合3 晕晕",
    "surprise": "晕晕眼",
    "default": "我也要死吗",
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


def pick_expression(text: str) -> str:
    key = detect_emotion(text)
    return EMOTION_MAP.get(key, EMOTION_MAP["default"])
