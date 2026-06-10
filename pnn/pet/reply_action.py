"""从台词推断 Live2D 动作（LLM 未打标签时的兜底）。"""

from __future__ import annotations

import re

from pnn.pet.actions import resolve_action_name

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"谢谢|感谢|对不起|抱歉|不好意思|ごめん|ありがと"), "bow"),
    (re.compile(r"太好|开心|高兴|兴奋|耶|哈哈|嘿嘿|太好了|やった|嬉し|楽し"), "sway"),
    (re.compile(r"嗯嗯|好的|知道了|没错|对呀|是这样|そう|うん"), "nod"),
    (re.compile(r"不行|不要|才不是|才不|不可能|别想了|讨厌|烦|むかつ|許さ"), "shake_head"),
    (re.compile(r"咦|诶\??|什么\??|真的吗|怎么会|なに|なぜ|どうして"), "tilt_head"),
    (re.compile(r"哇|天啊|不会吧|居然|惊讶|まさか|びっくり"), "surprise"),
    (re.compile(r"好累|困|伸个懒腰|睡醒|坐下|歇|疲惫|眠"), "sit"),
    (re.compile(r"伸懒|懒腰"), "stretch"),
    (re.compile(r"哼|开心哼|啦啦|～|ふふ|呵呵"), "sway"),
]


def infer_action_from_text(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw or len(raw) > 200:
        return None
    for pattern, action in _RULES:
        if pattern.search(raw):
            return resolve_action_name(action)
    return None
