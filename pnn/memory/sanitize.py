"""记忆入库前清理桌宠/LLM 表情标签，避免写入记忆库。"""

from __future__ import annotations

import re

_EXPRESSION_TAG = re.compile(r"【表情:([^】]+)】")


def strip_expression_tags(text: str) -> str:
    return _EXPRESSION_TAG.sub("", text or "").strip()


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
