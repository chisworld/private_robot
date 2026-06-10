"""从 presence daily_log 补检索过去对话，并在命中时回写记忆库。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from pnn.core.paths import DATA_DIR
from pnn.memory.sanitize import strip_expression_tags
from pnn.memory.store import MemoryStore, _keyword_similarity

logger = logging.getLogger(__name__)

_LOG_DIR = DATA_DIR / "presence" / "daily_log"
_LOG_DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})\.json$")

_PAST_TOPIC_RE = re.compile(
    r"(?:"
    r"昨天|前天|大前天|上次|之前|以前|先前|当时|那时|早些时候|有一[次回]|那次|那回|"
    r"咱们|我们一起|还记得|记得|记不记得|忘了|有没有|是不是|不是说|你说过|我说过|"
    r"之前说|上回|过往|以前的事|之前的事|继续.*(?:吧|吗|么)|再.*(?:一次|一遍|来)"
    r")",
    re.IGNORECASE,
)

_RECALL_STOP_WORDS = frozenset(
    {
        "什么",
        "怎么",
        "为什么",
        "是不是",
        "有没有",
        "可以",
        "一下",
        "我们",
        "你们",
        "他们",
        "这个",
        "那个",
        "然后",
        "还是",
        "就是",
        "已经",
        "现在",
        "今天",
        "明天",
        "真的",
        "知道",
        "觉得",
        "告诉",
        "请问",
    }
)


@dataclass(frozen=True)
class PresenceTurnHit:
    day: str
    at: str
    user: str
    assistant: str
    score: float


def is_past_topic_query(text: str) -> bool:
    """用户是否在提起过去发生的事（含隐式回调）。"""
    q = (text or "").strip()
    if not q:
        return False
    if _PAST_TOPIC_RE.search(q):
        return True
    if re.search(r"(?:不是|难道).{2,24}(?:吗|么|嘛)\s*$", q):
        return True
    return False


def extract_recall_keywords(text: str, *, limit: int = 8) -> list[str]:
    """从用户句中提取可用于多路检索的关键词。"""
    q = (text or "").strip()
    if not q:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in re.finditer(r"[\u4e00-\u9fff]{2,8}", q):
        w = m.group()
        if w in _RECALL_STOP_WORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def build_search_queries(
    user_message: str, *, assistant_name: str = ""
) -> list[str]:
    """构造多路检索 query（原句 + 扩展 + 关键词）。"""
    from pnn.memory.retrieval import expand_search_query

    q = (user_message or "").strip()
    if not q:
        return []
    queries = [q]
    expanded = expand_search_query(q, assistant_name=assistant_name)
    if expanded and expanded != q:
        queries.append(expanded)
    if is_past_topic_query(q):
        for kw in extract_recall_keywords(q):
            queries.append(kw)
    seen: set[str] = set()
    out: list[str] = []
    for item in queries:
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _list_recent_log_files(*, days: int = 14) -> list[Path]:
    if not _LOG_DIR.is_dir():
        return []
    cutoff = date.today() - timedelta(days=max(1, days))
    out: list[Path] = []
    for path in _LOG_DIR.glob("*.json"):
        m = _LOG_DATE_RE.search(path.name)
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if d >= cutoff:
            out.append(path)
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def _score_turn(query: str, user: str, assistant: str) -> float:
    blob = f"{user}\n{assistant}".strip().lower()
    if not blob or not query.strip():
        return 0.0
    q = query.strip().lower()
    base = _keyword_similarity(q, blob)
    bonus = 0.0
    for kw in extract_recall_keywords(query, limit=6):
        if len(kw) >= 2 and kw in blob:
            bonus += 0.08
    return base + bonus


def search_presence_logs(
    user_message: str,
    *,
    days: int = 14,
    max_hits: int = 6,
    min_score: float = 0.12,
) -> list[PresenceTurnHit]:
    """跨 session 扫描近期 daily_log，按相关度返回对话轮次。"""
    q = (user_message or "").strip()
    if not q:
        return []
    queries = build_search_queries(q)
    hits: list[PresenceTurnHit] = []
    seen: set[str] = set()

    for path in _list_recent_log_files(days=days):
        m = _LOG_DATE_RE.search(path.name)
        day = m.group(1) if m else ""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            user = str(item.get("user") or "").strip()
            assistant = str(item.get("assistant") or "").strip()
            if not user and not assistant:
                continue
            key = f"{day}|{user[:40]}|{assistant[:40]}"
            if key in seen:
                continue
            score = max(_score_turn(sq, user, assistant) for sq in queries)
            if score < min_score:
                continue
            seen.add(key)
            hits.append(
                PresenceTurnHit(
                    day=day,
                    at=str(item.get("at") or ""),
                    user=user,
                    assistant=assistant,
                    score=score,
                )
            )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:max_hits]


def format_presence_recall_block(hits: list[PresenceTurnHit]) -> str:
    if not hits:
        return ""
    lines: list[str] = []
    for h in hits:
        hh = h.at[11:16] if len(h.at) >= 16 else ""
        when = f"{h.day} {hh}".strip()
        if h.user and h.assistant:
            lines.append(f"- [{when}] 用户：{h.user} → 你：{h.assistant}")
        elif h.user:
            lines.append(f"- [{when}] 用户：{h.user}")
        else:
            lines.append(f"- [{when}] 你：{h.assistant}")
    return (
        "【近期真实对话记录·与本轮相关】\n"
        + "\n".join(lines)
        + "\n（以上来自当日会话存档，若与用户本轮问题相关，必须据此回应，不得否认发生过。）"
    )


def _prepare_presence_turn(user: str, assistant: str) -> tuple[str, str]:
    user = strip_expression_tags(user).strip()
    assistant = strip_expression_tags(assistant).strip()
    if not user or not assistant:
        return user, assistant
    try:
        from pnn.translate.service import translate_service

        if translate_service.is_enabled():
            assistant = translate_service.to_display_chinese(assistant)
    except Exception:
        pass
    return user, assistant


def backfill_presence_hits(
    store: MemoryStore,
    hits: list[PresenceTurnHit],
    *,
    user_label: str,
    assistant_label: str,
) -> int:
    """将命中的 presence 轮次补写入记忆库 dialogue，便于后续检索。"""
    written = 0
    for h in hits:
        user, assistant = _prepare_presence_turn(h.user, h.assistant)
        if not user or not assistant:
            continue
        block = f"{user_label}：{user}\n{assistant_label}：{assistant}"
        if store.has_exact_content(block, kind="dialogue"):
            continue
        try:
            store.add(block, kind="dialogue", importance=4.5, initial_score=0.92)
            written += 1
        except Exception as exc:
            logger.debug("presence 回写 dialogue 跳过: %s", exc)
    if written:
        logger.info("已从 presence 日志回写 %d 条对话到记忆库", written)
    return written
