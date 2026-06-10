"""记忆入库前清理桌宠/LLM 标签，避免写入记忆库。"""

from __future__ import annotations

import re

from pnn.pet.expression_tags import strip_expression_tags as _strip_pet_tags

# 主动搭话 / 系统触发时发给 LLM 的占位用户句，不应原样写入 [dialogue]
SYSTEM_PROACTIVE_USER_MARKERS = frozenset(
    {
        "（请根据系统背景主动开口，不要复述系统文本）",
    }
)

_PROACTIVE_CTX_SKIP_PREFIXES = (
    "[系统提醒",
    "[schedule]",
    "[clock]",
    "[weather]",
    "[weather-reply]",
)

# LLM 摘要里可能出现的「以笑嘻表情」等表述
_EXPR_PHRASE = re.compile(
    r"(以[^，。；、\n]{1,12}表情[，、]?|【表情:[^】]+】)"
)


def is_system_proactive_turn(user_message: str) -> bool:
    return (user_message or "").strip() in SYSTEM_PROACTIVE_USER_MARKERS


def is_idle_proactive_memory_user_line(user_message: str) -> bool:
    """空闲搭话/时段问候等系统触发轮次，不应写入 [dialogue]。"""
    line = (user_message or "").strip()
    return line.startswith("空闲搭话") or line.startswith("空闲对话")


def is_schedule_proactive_context(system_context: str) -> bool:
    """仅日程到点/爽约提醒（[schedule-reminder] 前缀），不含空闲搭话/回归等。"""
    return (system_context or "").lstrip().startswith("[schedule-reminder")


def proactive_memory_user_line(system_context: str) -> str:
    """主动搭话/日程提醒写入记忆库时的用户侧描述。"""
    ctx = (system_context or "").strip()
    prefix = "日程提醒" if is_schedule_proactive_context(ctx) else "空闲搭话"
    if not ctx:
        return prefix
    lines: list[str] = []
    for raw in ctx.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if any(ln.startswith(p) for p in _PROACTIVE_CTX_SKIP_PREFIXES):
            continue
        if "仅供角色反应" in ln and "勿当作用户原话" in ln:
            continue
        lines.append(ln)
    if not lines:
        return prefix
    summary = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if len(summary) > 220:
        summary = summary[:220].rstrip() + "…"
    return f"{prefix}·{summary}" if summary else prefix


def strip_expression_tags(text: str) -> str:
    """与桌宠气泡通道一致：剥离【表情/情绪/动作】等标签。"""
    return _strip_pet_tags(text)


def sanitize_chat_summary(text: str) -> str:
    """记忆 chat 摘要：去掉表情标签及「以×表情」类措辞。"""
    s = strip_expression_tags(text)
    s = _EXPR_PHRASE.sub("", s)
    s = re.sub(r"[，、]{2,}", "，", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
