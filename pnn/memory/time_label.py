"""记忆条目的相对时间标签（昨天/今天等）。"""

from __future__ import annotations

from datetime import datetime, timezone


def memory_record_date(created_at: str = "", updated_at: str = "") -> str:
    """记忆列表展示的日期：优先首次写入日（created_at），并按本地时区取日。"""
    for raw in (created_at, updated_at):
        text = (raw or "").strip()
        if not text:
            continue
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone().strftime("%Y-%m-%d")
        except ValueError:
            if len(text) >= 10:
                return text[:10]
    return ""


def memory_age_label(created_at: str, *, now: datetime | None = None) -> str:
    """根据 created_at 返回「今天/昨天/前天/N天前」。"""
    raw = (created_at or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ref = now or datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone()
        local_ref = ref.astimezone()
        day_delta = (local_ref.date() - local_dt.date()).days
        if day_delta <= 0:
            return "今天"
        if day_delta == 1:
            return "昨天"
        if day_delta == 2:
            return "前天"
        if day_delta <= 7:
            return f"{day_delta}天前"
        return local_dt.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def format_memory_line(*, kind: str, content: str, created_at: str = "") -> str:
    age = memory_age_label(created_at)
    date_part = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            date_part = dt.astimezone().strftime("%Y-%m-%d")
        except ValueError:
            date_part = ""
    if age and date_part:
        tag = f"{kind}·{age} {date_part}"
    elif age:
        tag = f"{kind}·{age}"
    else:
        tag = kind
    return f"- [{tag}] {content}"
