"""履约检测与日程闭环。"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from pnn.pet.presence.models import TimelineEventType
from pnn.pet.reminders.manager import get_reminder_manager
from pnn.pet.reminders.models import ReminderStatus

logger = logging.getLogger(__name__)

_FULFILLMENT_RE = re.compile(
    r"(我来了|到了|起床了|刚醒|准备好了|开始吃|一起吃|赴约|来赴约|"
    r"i'm here|here now|ready for breakfast)",
    re.IGNORECASE,
)


def looks_like_fulfillment(text: str) -> bool:
    return bool(_FULFILLMENT_RE.search((text or "").strip()))


def try_complete_schedules_in_window(
    user_text: str,
    session_key: str,
    *,
    now: datetime | None = None,
) -> list[str]:
    if not looks_like_fulfillment(user_text):
        return []
    ts = now or datetime.now()
    mgr = get_reminder_manager()
    completed: list[str] = []
    for r in mgr.list_for_session(session_key):
        if r.status != ReminderStatus.pending:
            continue
        end = r.effective_end()
        if r.scheduled_start <= ts <= end:
            if mgr.mark_completed(r.id):
                completed.append(r.id)
                logger.debug("schedule fulfilled: %s", r.title)
    return completed


def apply_fulfillment_effects(service: Any, session_key: str, user_text: str) -> bool:
    if not looks_like_fulfillment(user_text):
        return False
    ids = try_complete_schedules_in_window(user_text, session_key)
    service.adjust_trust(8)
    service.set_emotion("happy", "用户履约/出现了")
    summary = "用户履约出现"
    if ids:
        summary += f"（完成 {len(ids)} 项约定）"
    service.add_timeline(TimelineEventType.fulfillment, summary)
    return bool(ids)
