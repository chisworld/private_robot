"""轻量「我在做什么」上下文：番茄钟、窗口、待办。"""

from __future__ import annotations

from datetime import datetime

from pnn.pet.presence.models import SessionPresenceBundle
from pnn.pet.presence.pomodoro import PomodoroPhase, get_pomodoro_service


def build_activity_context_block(
    bundle: SessionPresenceBundle,
    session_key: str,
    *,
    now: datetime | None = None,
) -> str:
    ts = now or datetime.now()
    parts: list[str] = []
    st = bundle.state

    pomo = get_pomodoro_service().get_state(session_key)
    if pomo.phase == PomodoroPhase.focus.value:
        rem = max(0, pomo.remaining_seconds(ts))
        mins = max(1, (rem + 59) // 60)
        parts.append(f"用户正在番茄专注「{pomo.label}」，约剩 {mins} 分钟；请简短陪伴，勿长篇打扰。")
    elif pomo.phase == PomodoroPhase.break_.value:
        rem = max(0, pomo.remaining_seconds(ts))
        parts.append(f"用户在专注后的休息中（约剩 {max(1, rem // 60)} 分钟），可轻松聊几句。")

    if not st.window_focused:
        parts.append("聊天窗不在前台，用户可能在忙别的。")
    elif st.last_user_activity_at:
        idle_min = int((ts - st.last_user_activity_at).total_seconds() // 60)
        if idle_min >= 3:
            parts.append(f"用户约 {idle_min} 分钟未发消息。")

    sk = (session_key or st.session_key or "").strip()
    if sk:
        try:
            from pnn.pet.reminders.manager import get_reminder_manager
            from pnn.pet.reminders.models import ReminderStatus

            pending = get_reminder_manager().list_for_session(sk, status=ReminderStatus.pending)
            soon = [
                r for r in pending if 0 <= (r.scheduled_start - ts).total_seconds() <= 3600
            ]
            if soon:
                titles = "、".join(r.title for r in soon[:3])
                parts.append(f"一小时内待办：{titles}。")
        except Exception:
            pass

    if not parts:
        return ""
    return "当前状态：" + " ".join(parts)
