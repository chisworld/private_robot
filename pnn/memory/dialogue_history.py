"""只读对话历史：合并记忆库 dialogue 与 presence daily_log，按时间排序。"""

from __future__ import annotations

import json
import re
from datetime import datetime

from pnn.memory.presence_recall import _LOG_DATE_RE, _list_recent_log_files

_MERGE_SEP = re.compile(r"\n\n---\n\n+")


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


def _normalize_assistant_display(text: str) -> str:
    """展示用：日语助手台词尽量译成中文。"""
    raw = (text or "").strip()
    if not raw:
        return raw
    try:
        from pnn.translate.service import translate_service

        if translate_service.looks_japanese(raw):
            zh = translate_service.for_memory_storage(raw)
            if zh and zh.strip():
                return zh.strip()
    except Exception:
        pass
    return raw


def load_dialogue_history(
    *,
    store,
    user_label: str,
    assistant_label: str,
    days: int = 60,
    limit: int = 500,
    normalize_zh: bool = True,
) -> list[dict]:
    """返回按对话时间倒序排列的历史条目（含删除用 id）。"""
    seen: set[str] = set()
    entries: list[dict] = []

    for rec in store.list_all(0, kind="dialogue"):
        at = (rec.created_at or rec.updated_at or "").strip()
        pairs = _parse_dialogue_block(
            rec.content, user_label=user_label, assistant_label=assistant_label
        )
        for turn_index, (user, assistant) in enumerate(pairs):
            if not user and not assistant:
                continue
            key = _entry_key(at, user, assistant)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "at": at,
                    "user": user,
                    "assistant": assistant,
                    "source": "memory",
                    "memory_id": rec.id,
                    "turn_index": turn_index,
                }
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
        for log_index, item in enumerate(raw):
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
                {
                    "at": at,
                    "user": user,
                    "assistant": assistant,
                    "source": "presence",
                    "log_path": str(path),
                    "log_index": log_index,
                }
            )

    entries.sort(key=lambda e: e.get("at") or "", reverse=True)
    out: list[dict] = []
    for e in entries[: max(1, limit)]:
        at = str(e.get("at") or "")
        user = str(e.get("user") or "")
        assistant = str(e.get("assistant") or "")
        if normalize_zh:
            assistant_display = _normalize_assistant_display(assistant)
        else:
            assistant_display = assistant
        row = {
            "at": at,
            "display_time": _format_display_time(at),
            "user": user,
            "assistant": assistant_display,
            "assistant_stored": assistant,
            "source": e.get("source") or "",
        }
        if e.get("memory_id"):
            row["memory_id"] = e["memory_id"]
            row["turn_index"] = int(e.get("turn_index") or 0)
        if e.get("log_path"):
            row["log_path"] = e["log_path"]
            row["log_index"] = int(e.get("log_index") or 0)
        out.append(row)
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
