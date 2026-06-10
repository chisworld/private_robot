"""记忆检索：问句扩展、脏数据判定、命中去重。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pnn.memory.store import MemoryRecord

# 入库/检索均降权或拒绝
NEGATIVE_MEMORY_MARKERS: tuple[str, ...] = (
    "没有记忆",
    "没有相关记忆",
    "想不起来",
    "完全不知道",
    "完全不知情",
    "不知情",
    "记忆芯片",
    "系统在耍",
    "怀疑主人在开玩笑",
    "困惑地表示",
    "感到困惑和混乱",
)

# 问句 → 检索扩展词（通用词面，不含任何固定角色名/人名）
_QUERY_EXPANSIONS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"妹妹|小妹"), ("妹妹", "家人")),
    (re.compile(r"姐姐|大姐"), ("姐姐", "家人")),
    (re.compile(r"弟弟|兄弟|哥哥"), ("弟弟", "哥哥", "家人")),
    (re.compile(r"叫什么|名字|姓名"), ("名字", "叫")),
    (re.compile(r"什么时候|何时|哪天"), ("时候", "之前", "告诉")),
    (re.compile(r"喜欢|爱好|偏好"), ("喜欢", "爱好")),
    (re.compile(r"记得|还记得|记不记得|忘了|有没有"), ("之前", "当时", "说过", "做过")),
    (re.compile(r"昨天|前天|上次|之前"), ("昨天", "之前", "当时")),
    (re.compile(r"osu|音游|节奏"), ("osu", "胜负", "赌", "赢", "输", "比赛")),
    (re.compile(r"赢|输了|赌|约"), ("赢", "输", "赌约", "约定", "胜负")),
    (re.compile(r"继续|再来|又一次|再玩|再比"), ("之前", "上次", "当时", "一起")),
    (re.compile(r"那[次回]|当时|那时"), ("那次", "当时", "之前", "说过")),
)


def active_assistant_label() -> str:
    """当前激活角色在记忆库中的助手称呼（pack.json 的 name，否则 id）。"""
    try:
        from pnn.characters.pack import load_pack
        from pnn.llm.config_store import load_llm_config

        cid = (load_llm_config().active_character or "").strip()
        if not cid:
            return "助手"
        pack = load_pack(cid)
        if pack is None:
            return cid
        return (pack.name or pack.id or "助手").strip() or "助手"
    except Exception:
        return "助手"


def is_negative_memory(content: str) -> bool:
    """假遗忘 / 纯情绪困惑摘要，不宜作为可检索事实。"""
    c = (content or "").strip()
    if not c:
        return False
    if any(m in c for m in NEGATIVE_MEMORY_MARKERS):
        return True
    # 「询问…表示没有…」类 chat 摘要
    if re.search(r"询问.*(?:没有|不知|想不起)", c):
        return True
    if re.search(r"表示.*(?:没有相关|完全不知道|想不起来)", c):
        return True
    return False


def expand_search_query(user_message: str, *, assistant_name: str | None = None) -> str:
    """将口语问句扩展为更利于关键词匹配的检索串。

    assistant_name 默认取当前激活角色包 name/id，换角色后自动切换，无需写死。
    """
    q = (user_message or "").strip()
    if not q:
        return q
    parts = [q]
    name = (assistant_name if assistant_name is not None else active_assistant_label()).strip()
    if name and name != "助手" and re.search(r"[你您]", q):
        parts.append(name)
        if "妹妹" in q:
            parts.append(f"{name}的妹妹")
        if "姐姐" in q:
            parts.append(f"{name}的姐姐")
        if "弟弟" in q:
            parts.append(f"{name}的弟弟")
        if "哥哥" in q:
            parts.append(f"{name}的哥哥")
    for pattern, extras in _QUERY_EXPANSIONS:
        if pattern.search(q):
            parts.extend(extras)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return " ".join(out)


def dedupe_hits(hits: list[MemoryRecord], *, threshold: float = 0.78) -> list[MemoryRecord]:
    """去掉内容高度重复的命中，避免 prompt 塞满同义句。"""
    from pnn.memory.store import _keyword_similarity

    out: list[MemoryRecord] = []
    for rec in hits:
        c = rec.content.strip().lower()
        if not c:
            continue
        dup_idx: int | None = None
        for i, kept in enumerate(out):
            k = kept.content.strip().lower()
            if c == k or c in k or k in c:
                dup_idx = i
                break
            if _keyword_similarity(c, k) >= threshold:
                dup_idx = i
                break
        if dup_idx is None:
            out.append(rec)
            continue
        kept = out[dup_idx]
        if len(rec.content) > len(kept.content):
            out[dup_idx] = rec
    return out
