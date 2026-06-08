"""构建各类 presence 系统触发文本。"""

from __future__ import annotations

from datetime import datetime, timedelta

from pnn.pet.presence.activity_context import build_activity_context_block
from pnn.pet.presence.config import load_presence_config
from pnn.pet.presence.intimacy import intimacy_tone_hint
from pnn.pet.presence.life_context import build_life_context_block
from pnn.pet.presence.models import EmotionMood, SessionPresenceBundle, UserLifeProfile


def _fmt_absence(last: datetime | None, now: datetime) -> str:
    if last is None:
        return "这是用户近期第一次打开会话。"
    delta = now - last
    if delta < timedelta(minutes=30):
        return "用户刚刚还在，分别时间很短。"
    if delta < timedelta(hours=6):
        return f"用户离开了约 {int(delta.total_seconds() // 3600) or 1} 小时。"
    days = delta.days
    if days >= 1:
        return f"用户已有 {days} 天没出现。"
    return f"用户离开了约 {int(delta.total_seconds() // 3600)} 小时。"


def _profile_hints(profile: UserLifeProfile) -> str:
    lines: list[str] = []
    if profile.preferred_name:
        lines.append(f"用户希望被称呼：{profile.preferred_name}。")
    if profile.taboos:
        lines.append("用户雷点（勿触碰）：" + "；".join(profile.taboos[:5]) + "。")
    if profile.preferences:
        prefs = "；".join(f"{k}={v}" for k, v in list(profile.preferences.items())[:6])
        lines.append(f"用户偏好：{prefs}。")
    if profile.char_catchphrases:
        lines.append("角色口癖参考：" + "、".join(profile.char_catchphrases[:4]) + "。")
    return "\n".join(lines)


def _emotion_hints(mood: EmotionMood, reason: str, trust: int) -> str:
    mood_zh = {
        EmotionMood.neutral: "平常",
        EmotionMood.happy: "开心",
        EmotionMood.annoyed: "有点生气/委屈",
        EmotionMood.sad: "难过",
        EmotionMood.worried: "担心",
        EmotionMood.sleepy: "困倦",
    }.get(mood, "平常")
    text = f"角色当前情绪：{mood_zh}（信任度 {trust}/100）。"
    if reason:
        text += f"原因：{reason}。"
    return text


def _timeline_hints(events: list, limit: int = 5) -> str:
    if not events:
        return ""
    recent = sorted(events, key=lambda e: e.occurred_at, reverse=True)[:limit]
    lines = [f"- {e.occurred_at:%m-%d %H:%M} {e.summary}" for e in recent]
    return "近期事件时间线：\n" + "\n".join(lines)


def _pending_schedule_hint(bundle: SessionPresenceBundle) -> str:
    """注入真实待办列表，避免 LLM 在无日程时编造「忘记约定」。"""
    sk = (bundle.state.session_key or "").strip()
    if not sk:
        return "当前无进行中的日程待办；勿编造用户忘记或爽约某约定。"
    try:
        from pnn.pet.reminders.manager import get_reminder_manager
        from pnn.pet.reminders.models import ReminderStatus

        pending = get_reminder_manager().list_for_session(sk, status=ReminderStatus.pending)
        if not pending:
            return "当前无进行中的日程待办；勿编造用户忘记或爽约某约定。"
        titles = "、".join(r.title for r in pending[:5])
        return f"当前待办：{titles}。"
    except Exception:
        return "当前无进行中的日程待办；勿编造用户忘记或爽约某约定。"


def build_presence_trigger(
    kind: str,
    bundle: SessionPresenceBundle,
    *,
    now: datetime | None = None,
    extra: str = "",
    session_key: str = "",
) -> str:
    ts = now or datetime.now()
    st = bundle.state
    sk = (session_key or st.session_key or "").strip()
    char = st.character_name or "当前角色"
    cfg = load_presence_config()
    life = build_life_context_block(ts)
    activity = build_activity_context_block(bundle, sk, now=ts)
    absence = _fmt_absence(st.last_session_seen_at, ts)
    profile = _profile_hints(bundle.profile)
    emotion = _emotion_hints(st.emotion_mood, st.emotion_reason, st.trust_level)
    intimacy = intimacy_tone_hint(st.trust_level, st.emotion_mood) if cfg.intimacy_enabled else ""
    timeline = _timeline_hints(bundle.timeline)

    if kind == "idle":
        lead = (
            "用户一段时间没有发消息，但程序仍在运行。"
            "请以角色身份自然找话题，像真人一样随口搭话，不要像通知。"
        )
    elif kind == "afk":
        lead = (
            "用户长时间挂机未互动。"
            "请用更轻、更短的语气（一句即可），可以关心或安静陪伴，不要长篇大论。"
        )
    elif kind == "return_focus":
        lead = "用户刚刚把窗口切回前台/取消最小化。请自然打招呼或接续之前话题。"
    elif kind == "absence_return":
        lead = (
            f"用户重新打开会话。{absence}"
            "请根据分别时长调整语气（久别重逢 vs 刚分开）。"
            "若当前没有进行中的日程待办，不要编造用户忘记或爽约某约定。"
        )
    elif kind == "fulfillment":
        lead = (
            "用户刚刚履约（如赴约、说「我来了」）。"
            "请表达开心、被在乎的感觉，并自然继续约定相关话题。"
        )
    elif kind == "interrupt":
        lead = (
            "用户连续快速发送多条消息。"
            "请先插一句简短口语（如「等一下啦」），再回答实质内容。"
        )
    elif kind == "time_greeting":
        lead = (
            "这是本时段的首次见面问候（早/午/晚等）。"
            "请自然问好一句，可结合天气或周末，不要像闹钟通知。"
        )
    elif kind == "holiday_greeting":
        lead = (
            "今天是特殊日子（节日或用户生日）。"
            "请真诚祝贺或关心一句，语气符合角色，不要套话堆砌。"
        )
    elif kind == "pomodoro_focus_end":
        lead = (
            "用户刚完成一段番茄专注。"
            "请简短庆祝并提醒休息；可配合伸懒腰类动作语气。"
        )
    elif kind == "pomodoro_break_end":
        lead = (
            "用户专注后的短休息结束。"
            "可问是否继续下一轮或聊点轻松的。"
        )
    elif kind == "daily_summary":
        lead = "用户想了解今天聊过什么。请根据下方要点简要回顾，勿逐条朗读。"
    elif kind == "context":
        lead = "（以下为角色背景上下文，供你保持一致，勿逐字复读。）"
    else:
        lead = extra or "请以角色身份自然回应。"

    blocks = [
        "[系统提醒 · 仅供角色反应，勿当作用户原话]",
        _pending_schedule_hint(bundle),
        life,
        activity,
        absence,
        emotion,
        intimacy,
        profile,
        timeline,
        f"主要反应角色：{char}。",
        lead,
        "不要复读本段系统文本。",
    ]
    if extra and kind not in ("interrupt",):
        blocks.insert(-2, extra)
    return "\n".join(b for b in blocks if b)
