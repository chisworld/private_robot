"""避免把「助手回忆旧闻」误提取为新 event/fact。"""

from __future__ import annotations

import re

_RECALL_STOPWORDS = frozenset(
    {
        "哥哥",
        "主人",
        "里想奈",
        "助手",
        "很",
        "担心",
        "需要",
        "已经",
        "今天",
        "昨天",
        "明天",
        "表示",
        "觉得",
        "可能",
        "应该",
        "适合",
        "一起",
        "一直",
        "陪伴",
        "承诺",
    }
)


def _significant_terms(text: str) -> list[str]:
    """从文本拆出可匹配的话题词（含长串的二/三元组，避免「被毒蛙咬了」整段对不上「被毒蛙咬了吗」）。"""
    out: list[str] = []
    seen: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text or ""):
        candidates = [run]
        if len(run) > 2:
            for size in (2, 3):
                for i in range(len(run) - size + 1):
                    candidates.append(run[i : i + size])
        for t in candidates:
            if len(t) < 2 or t in _RECALL_STOPWORDS or t in seen:
                continue
            seen.add(t)
            out.append(t)
    return out


def _term_in_text(term: str, text: str) -> bool:
    return (term or "") in (text or "")


def is_recall_only_extraction(
    user_message: str,
    assistant_reply: str,
    content: str,
) -> bool:
    """用户本轮未提新事实，内容主要来自助手对旧事的提醒/回忆。"""
    user = (user_message or "").strip()
    assistant = (assistant_reply or "").strip()
    extracted = (content or "").strip()
    if not user or not extracted:
        return False

    terms = _significant_terms(extracted)
    if not terms:
        return False

    user_hits = sum(1 for t in terms if _term_in_text(t, user))
    if user_hits >= max(1, len(terms) // 4):
        return False

    assistant_only = [
        t for t in terms if _term_in_text(t, assistant) and not _term_in_text(t, user)
    ]
    return len(assistant_only) >= 1
