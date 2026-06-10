"""只读对话历史：合并记忆库 dialogue 与 presence daily_log，按时间排序。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from pnn.memory.presence_recall import _LOG_DATE_RE, _list_recent_log_files

_MERGE_SEP = re.compile(r"\n\n---\n\n+")


@dataclass(frozen=True)
class DialogueHistoryEntry:
    at: str
    user: str
    assistant: str
    source: str


def _parse_dialogue_block(
    content: str, *, user_label: str, assistant_label: str
) -> list[tuple[str, str]]:
    """从 [dialogue] 正文解析一轮或多轮 user/assistant。"""
    text = (content or "").strip()
    if not text:
        return []
    blocks = _MERGE_SEP.split(text) if _MERGE_SEP.search(text) else [text]
    out: list[tuple[str, str]] = []
    u_prefix = f"{user_label}："
    a_prefix = f"{assistant_label}："
    for block in blocks:
        user = ""
        assistant = ""
        for line in block.splitlines():
            line = line.strip()
            if line.startswith(u_prefix):
                user = line[len(u_prefix) :].strip()
            elif line.startswith(a_prefix):
                assistant = line[len(a_prefix) :].strip()
        if user or assistant:
            out.append((user, assistant))
    return out


def _entry_key(at: str, user: str, assistant: str) -> str:
    return f"{at[:16]}|{user[:48]}|{assistant[:48]}"


def load_dialogue_history(
    *,
    store,
    user_label: str,
    assistant_label: str,
    days: int = 60,
    limit: int = 500,
) -> list[dict]:
    """返回按对话时间倒序排列的只读历史条目。"""
    seen: set[str] = set()
    entries: list[DialogueHistoryEntry] = []

    for rec in store.list_all(0, kind="dialogue"):
        at = (rec.created_at or rec.updated_at or "").strip()
        for user, assistant in _parse_dialogue_block(
            rec.content, user_label=user_label, assistant_label=assistant_label
        ):
            if not user and not assistant:
                continue
            key = _entry_key(at, user, assistant)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                DialogueHistoryEntry(
                    at=at,
                    user=user,
                    assistant=assistant,
                    source="memory",
                )
            )

    log_days = max(1, int(days))
    for path in _list_recent_log_files(days=log_days):
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
            at = str(item.get("at") or "").strip() or f"{day}T00:00:00"
            key = _entry_key(at, user, assistant)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                DialogueHistoryEntry(
                    at=at,
                    user=user,
                    assistant=assistant,
                    source="presence",
                )
            )

    def _sort_key(entry: DialogueHistoryEntry) -> str:
        return entry.at or ""

    entries.sort(key=_sort_key, reverse=True)
    out: list[dict] = []
    for e in entries[: max(1, limit)]:
        display_time = _format_display_time(e.at)
        out.append(
            {
                "at": e.at,
                "display_time": display_time,
                "user": e.user,
                "assistant": e.assistant,
                "source": e.source,
            }
        )
    return out


def _format_display_time(at: str) -> str:
    raw = (at or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        if len(raw) >= 16:
            return raw[:16].replace("T", " ")
        return raw[:10]
