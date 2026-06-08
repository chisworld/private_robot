"""亲密度 / 小脾气：信任度与语气提示。"""

from __future__ import annotations

import re
from collections.abc import Callable

from pnn.pet.presence.models import EmotionMood

_STRONG_POSITIVE_RE = re.compile(r"(最喜欢你|超喜欢你|爱你|最好了)")
_POSITIVE_RE = re.compile(r"(谢谢|辛苦|对不起.*原谅|喜欢你|真棒|厉害)")
_NEGATIVE_RE = re.compile(r"(放鸽子|爽约|骗人|生气|讨厌你|不理你|烦死了|滚)")
_MILD_NEGATIVE_RE = re.compile(r"(哼|才不是|笨蛋|讨厌)")


def apply_trust_from_user_message(adjust_trust: Callable[[int], None], text: str) -> None:
    body = text or ""
    if _STRONG_POSITIVE_RE.search(body):
        adjust_trust(6)
    elif _POSITIVE_RE.search(body):
        adjust_trust(3)
    elif _NEGATIVE_RE.search(body):
        adjust_trust(-8)
    elif _MILD_NEGATIVE_RE.search(body):
        adjust_trust(-2)


def intimacy_tone_hint(trust: int, mood: EmotionMood) -> str:
    trust = max(0, min(100, int(trust)))
    if trust >= 85:
        base = "亲密度很高：可以更撒娇、偶尔小任性，但仍要关心用户。"
    elif trust >= 65:
        base = "关系不错：语气自然亲近，可偶尔打趣。"
    elif trust >= 40:
        base = "关系平常：保持友好，不要过度热情或过度冷淡。"
    else:
        base = "信任偏低：语气稍收敛，若用户曾爽约可带一点小委屈，但不要攻击。"
    if mood == EmotionMood.annoyed:
        base += " 当前略有小脾气，一句带过即可，勿长篇抱怨。"
    elif mood == EmotionMood.happy:
        base += " 心情不错，可更活泼。"
    elif mood == EmotionMood.sad:
        base += " 有点难过，可寻求安慰但仍要回应用户。"
    return base
