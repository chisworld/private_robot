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
    start_clock = start.split()[1] if " " in start else start
    if trigger_kind == "missed":
        lead = (
            f"约定「{reminder.title}」的时间窗口（{start} 至 {end}）已结束。"
            "当时用户未打开桌宠，到点提醒未能送达。"
        )
        tone = (
            f"请以角色身份主动开口，自然表达失望、抱怨、委屈或轻微生气，"
            f"质问或吐槽用户为何忘记这次约定（{start_clock} 的{reminder.title}），并询问原因；"
            "不要轻描淡写带过。"
        )
    elif trigger_kind == "due_start":
        lead = (
            f"约定「{reminder.title}」的时间到了（{start} 至 {end}）。"
            "桌宠正在运行，用户此时在场。"
        )
        tone = (
            f"请以角色身份主动提醒用户履行约定；须明确提到约定时间 {start_clock}。"
            "邀请或提醒用户现在一起完成；语气自然，不要像系统通知。"
        )
    else:
        lead = (
            f"约定「{reminder.title}」正在进行中（{start} 至 {end}）。"
        )
        tone = "请以角色身份主动提起这次约定，温和提醒或邀请用户一起完成。"

    extra = ""
    if reminder.description:
        extra = f"\n补充说明：{reminder.description}"

    launch_hint = _build_launch_app_hint(reminder)
    if launch_hint:
        extra += launch_hint

    return (
        "[schedule-reminder · 仅供角色反应，勿当作用户原话]\n"
        f"{lead}{extra}\n"
        f"主要反应角色：{char}。\n"
        f"{tone}不要复读本段系统文本。"
    )


def _build_launch_app_hint(reminder: Reminder) -> str:
    app_id = (reminder.launch_app_id or "").strip()
    if not app_id:
        return ""
    label = app_id
    try:
        from pnn.launch_apps.service import launch_apps_service

        entry = launch_apps_service.get_app_by_id(app_id) or launch_apps_service.resolve_app(app_id)
        if entry is not None:
            label = entry.label or entry.id
    except Exception:
        logger.debug("读取快捷启动项失败", exc_info=True)
    return (
        f"\n关联快捷启动：{label}（id={app_id}）。"
        f"到点后将自动为用户打开{label}；"
        f"同时请以角色身份自然开口提醒，可顺带确认是否开始。"
    )


def build_greet_on_open_text() -> str:
    return (
        "[系统提醒 · 仅供角色反应，勿当作用户原话]\n"
        "用户刚刚打开了聊天窗口，尚未输入任何消息。\n"
        "请以角色身份自然打招呼或延续近期话题，不要复读本段系统文本。"
    )


def _auto_launch_bound_app(reminder: Reminder) -> None:
    app_id = (reminder.launch_app_id or "").strip()
    if not app_id:
        return
    try:
        from pnn.launch_apps.service import launch_apps_service

        result = launch_apps_service.call_launch_app({"app": app_id})
        logger.info(
            "[schedule] 到点自动启动 %s: %s",
            reminder.title,
            (result or "")[:120],
        )
    except Exception:
        logger.exception("到点自动启动失败: %s", app_id)


def _dispatch_one_trigger(
    reminder: Reminder,
    trigger_kind: str,
    mgr,
    *,
    emit_proactive: Callable[[str], bool],
) -> bool:
    rid = reminder.id
    if trigger_kind == "missed":
        claimed = mgr.claim_missed_complaint(rid)
        if claimed is None:
            logger.debug("爽约抱怨已认领或不存在，跳过: %s", reminder.title)
            return False
        reminder = claimed

    text = build_reminder_trigger_text(reminder, trigger_kind)
    try:
        text = text + "\n" + build_presence_trigger("context", get_presence_service().bundle)
    except Exception:
        logger.debug("附加 presence 上下文失败", exc_info=True)

    if not emit_proactive(text):
        logger.warning(
            "日程提醒未能派发（%s · %s），将稍后重试",
            trigger_kind,
            reminder.title,
        )
        if trigger_kind == "missed":
            mgr.release_missed_complaint(rid)
        return False

    logger.info(
        "[schedule] 已派发 %s 提醒: %s @ %s",
        trigger_kind,
        reminder.title,
        reminder.scheduled_start.strftime("%H:%M"),
    )

    if trigger_kind == "due_start":
        _auto_launch_bound_app(reminder)
        # 到点提醒成功送达 = 用户在场赴约；删除待办，不再追讨
        mgr.delete(reminder.id)
        logger.info("[schedule] 到点提醒已送达，待办已删除: %s", reminder.title)
    elif trigger_kind == "missed":
        try:
            get_presence_service().on_missed_appointment(reminder.title)
        except Exception:
            logger.debug("missed appointment 回调失败", exc_info=True)
        if not mgr.delete(reminder.id):
            logger.warning("爽约抱怨已派发但删除待办失败: %s", reminder.id)
    return True


def run_background_triggers(
    *,
    session_key: str,
    emit_proactive: Callable[[str], bool],
    now: datetime | None = None,
) -> int:
    """后台轮询：仅在约定窗口内尝试到点提醒（不在这里处理爽约）。"""
    cfg = load_presence_config()
    if not cfg.schedule_background_monitor or not is_schedule_runtime_ready():
        if cfg.schedule_background_monitor and not is_schedule_runtime_ready():
            logger.debug("日程触发推迟：API/LLM 未就绪")
        return 0

    ts = now or datetime.now()
    mgr = get_reminder_manager()
    mgr.purge_ended_reminders(session_key, now=ts)
    for reminder, kind in sorted(
        mgr.find_due_triggers(session_key, now=ts),
        key=lambda x: x[0].scheduled_start,
    ):
        if _dispatch_one_trigger(reminder, kind, mgr, emit_proactive=emit_proactive):
            return 1
    return 0


def run_overdue_missed_on_ready(
    *,
    session_key: str,
    emit_proactive: Callable[[str], bool],
    now: datetime | None = None,
) -> int:
    """桌宠/API 就绪后：检查已过期的未提醒待办，爽约抱怨后删除。"""
    if not is_schedule_runtime_ready():
        logger.debug("过期日程检查推迟：API/LLM 未就绪")
        return 0

    ts = now or datetime.now()
    mgr = get_reminder_manager()
    mgr.purge_ended_reminders(session_key, now=ts)
    overdue = sorted(
        mgr.find_overdue_missed(session_key, now=ts),
        key=lambda x: x[0].scheduled_start,
    )
    count = 0
    for reminder, kind in overdue:
        if _dispatch_one_trigger(reminder, kind, mgr, emit_proactive=emit_proactive):
            count += 1
    return count


def run_auto_triggers_on_window_open(
    *,
    session_key: str,
    emit_proactive: Callable[[str], bool],
    fresh_session: bool = False,
) -> int:
    """打开对话窗：优先处理过期爽约，可选问候。"""
    if not is_schedule_runtime_ready():
        return 0

    cfg = load_presence_config()
    auto_greet = cfg.schedule_auto_greet_on_open
    if fresh_session:
        auto_greet = False

    n = 0
    if cfg.schedule_auto_trigger_on_open:
        n = run_overdue_missed_on_ready(
            session_key=session_key,
            emit_proactive=emit_proactive,
        )
    if n:
        return n

    if auto_greet:
        svc = get_presence_service()
        if svc.recently_proactive(within_seconds=300):
            logger.debug("跳过开窗问候：刚已主动搭话")
            return 0
        if svc.should_resume_session():
            logger.debug("跳过开窗问候：近期有对话可续")
            return 0
        text = build_greet_on_open_text()
        try:
            from pnn.pet.presence.triggers import build_presence_trigger

            text = text + "\n" + build_presence_trigger(
                "window_greet", svc.bundle, session_key=session_key
            )
        except Exception:
            pass
        svc.mark_trigger_kind("window_greet")
        if emit_proactive(text):
            return 1
        svc.mark_trigger_kind("")

    return 0
