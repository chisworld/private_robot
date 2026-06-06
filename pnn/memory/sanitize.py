"""记忆入库前清理桌宠/LLM 标签，避免写入记忆库。"""

from __future__ import annotations

import re

from pnn.pet.expression_tags import strip_expression_tags as _strip_pet_tags

# 主动搭话 / 系统触发时发给 LLM 的占位用户句，不应写入 [dialogue]
SYSTEM_PROACTIVE_USER_MARKERS = frozenset(
    {
        "（请根据系统背景主动开口，不要复述系统文本）",
    }
)


def strip_expression_tags(text: str) -> str:
    """与桌宠气泡通道一致：剥离【表情/情绪/动作】等标签。"""
    return _strip_pet_tags(text)


def is_system_proactive_turn(user_message: str) -> bool:
    return (user_message or "").strip() in SYSTEM_PROACTIVE_USER_MARKERS


# LLM 摘要里可能出现的「以笑嘻表情」等表述
_EXPR_PHRASE = re.compile(
    r"(以[^，。；、\n]{1,12}表情[，、]?|【表情:[^】]+】)"
)


def sanitize_chat_summary(text: str) -> str:
    """记忆 chat 摘要：去掉表情标签及「以×表情」类措辞。"""
    s = strip_expression_tags(text)
    s = _EXPR_PHRASE.sub("", s)
    s = re.sub(r"[，、]{2,}", "，", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
