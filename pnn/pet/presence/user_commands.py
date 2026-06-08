"""用户口令：番茄钟、今日摘要等。"""

from __future__ import annotations

import logging

from pnn.pet.presence.config import load_presence_config
from pnn.pet.presence.daily_log import build_daily_summary_text, is_daily_summary_query
from pnn.pet.presence.pomodoro import (
    get_pomodoro_service,
    parse_pomodoro_start_minutes,
    parse_pomodoro_stop,
)

logger = logging.getLogger(__name__)


def handle_user_commands(text: str, session_key: str) -> str:
    """解析用户口令，返回需注入 LLM 的前缀（空串表示无）。"""
    raw = (text or "").strip()
    if not raw:
        return ""

    cfg = load_presence_config()

    if is_daily_summary_query(raw):
        if not cfg.daily_summary_enabled:
            return ""
        summary = build_daily_summary_text(session_key)
        return (
            "[companion] 用户询问今天聊过什么。\n"
            f"{summary}\n"
            "请用角色口吻简要回顾 2–4 条要点，不要像列表朗读。"
        )

    if parse_pomodoro_stop(raw):
        if not cfg.pomodoro_enabled:
            return ""
        get_pomodoro_service().stop(session_key)
        return "[companion] 用户已结束番茄专注。请简短确认并关心是否要休息。"

    mins = parse_pomodoro_start_minutes(raw)
    if mins is not None and cfg.pomodoro_enabled:
        st = get_pomodoro_service().start(session_key, mins)
        return (
            "[companion] 用户开始番茄专注陪伴。\n"
            f"专注 {st.work_minutes} 分钟，结束后休息 {st.break_minutes} 分钟。\n"
            "请鼓励一句并说明你会安静陪伴；专注期间回复尽量短，不要频繁搭话。"
        )

    return ""
