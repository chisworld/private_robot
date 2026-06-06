"""日程自动触发文本与派发。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from pnn.pet.presence.config import load_presence_config
from pnn.pet.presence.service import get_presence_service
from pnn.pet.presence.triggers import build_presence_trigger
from pnn.pet.reminders.manager import get_reminder_manager
from pnn.pet.reminders.models import Reminder
from pnn.pet.reminders.readiness import is_schedule_runtime_ready

logger = logging.getLogger(__name__)


def _fmt_dt(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M")


def build_reminder_trigger_text(reminder: Reminder, trigger_kind: str) -> str:
    start = _fmt_dt(reminder.scheduled_start)
    end = _fmt_dt(reminder.effective_end())
    char = reminder.character_name or "当前角色"
    if trigger_kind == "missed":
        lead = (
            f"约定「{reminder.title}」的时间窗口（{start} 至 {end}）已结束，"
            "用户在该时段内未出现、也未履约。"
        )
        tone = "请以角色身份主动开口，自然表达失望、抱怨或委屈，并询问原因。"
    elif trigger_kind == "due_start":
        lead = (
            f"约定「{reminder.title}」的时间到了（{start} 至 {end}）。"
            "用户可能刚打开窗口，也可能程序在后台运行中。"
        )
        tone = "请以角色身份主动提起这次约定，邀请或提醒用户现在一起履约。"
    else:
        lead = (
            f"约定「{reminder.title}」正在进行中（{start} 至 {end}），"
            "用户刚刚打开窗口。"
        )
        tone = "请以角色身份主动提起这次约定，温和提醒或邀请用户一起完成。"

    extra = ""
    if reminder.description:
        extra = f"\n补充说明：{reminder.description}"

    return (
        "[系统提醒 · 仅供角色反应，勿当作用户原话]\n"
        f"{lead}{extra}\n"
        f"主要反应角色：{char}。\n"
        f"{tone}不要复读本段系统文本。"
    )


def build_greet_on_open_text() -> str:
    return (
        "[系统提醒 · 仅供角色反应，勿当作用户原话]\n"
        "用户刚刚打开了聊天窗口，尚未输入任何消息。\n"
        "请以角色身份自然打招呼或延续近期话题，不要复读本段系统文本。"
    )


def _dispatch_one_trigger(
    reminder: Reminder,
    trigger_kind: str,
    mgr,
    *,
    emit_proactive: Callable[[str], None],
) -> None:
    text = build_reminder_trigger_text(reminder, trigger_kind)
    try:
        text = text + "\n" + build_presence_trigger("context", get_presence_service().bundle)
    except Exception:
        logger.debug("附加 presence 上下文失败", exc_info=True)

    emit_proactive(text)

    if trigger_kind == "due_start":
        mgr.mark_start_notified(reminder)
    elif trigger_kind == "missed":
        mgr.mark_triggered(reminder, as_missed=True)
        try:
            get_presence_service().on_missed_appointment(reminder.title)
        except Exception:
            logger.debug("missed appointment 回调失败", exc_info=True)


def run_background_triggers(
    *,
    session_key: str,
    emit_proactive: Callable[[str], None],
) -> int:
    cfg = load_presence_config()
    if not cfg.schedule_background_monitor or not is_schedule_runtime_ready():
        return 0

    mgr = get_reminder_manager()
    for reminder, kind in sorted(
        mgr.find_background_triggers(session_key),
        key=lambda x: (0 if x[1] == "missed" else 1, x[0].scheduled_start),
    ):
        _dispatch_one_trigger(reminder, kind, mgr, emit_proactive=emit_proactive)
        return 1
    return 0


def run_auto_triggers_on_window_open(
    *,
    session_key: str,
    emit_proactive: Callable[[str], None],
    fresh_session: bool = False,
) -> int:
    if not is_schedule_runtime_ready():
        return 0

    cfg = load_presence_config()
    auto_schedule = cfg.schedule_auto_trigger_on_open
    auto_greet = cfg.schedule_auto_greet_on_open
    nudge = cfg.schedule_nudge_during_window

    if fresh_session:
        auto_greet = False

    if not auto_schedule and not auto_greet:
        return 0

    mgr = get_reminder_manager()

    if auto_schedule:
        for reminder, kind in mgr.find_open_triggers(session_key, nudge_during_window=nudge):
            _dispatch_one_trigger(reminder, kind, mgr, emit_proactive=emit_proactive)
            if kind == "nudge":
                mgr.mark_start_notified(reminder)
            return 1

    if auto_greet:
        text = build_greet_on_open_text()
        try:
            text = text + "\n" + build_presence_trigger("context", get_presence_service().bundle)
        except Exception:
            pass
        emit_proactive(text)
        return 1

    return 0
