"""在场感核心服务。"""

from __future__ import annotations

import logging
import random
import re
from collections.abc import Callable
from datetime import datetime

from pnn.pet.presence.config import PresenceConfig, load_presence_config
from pnn.pet.presence.fulfillment import apply_fulfillment_effects
from pnn.pet.presence.interrupt import InterruptTracker
from pnn.pet.presence.models import EmotionMood, SessionPresenceBundle, TimelineEvent, TimelineEventType
from pnn.pet.presence.profile import sync_profile_from_turn
from pnn.pet.presence.store import load_bundle, save_bundle
from pnn.pet.presence.triggers import build_presence_trigger
from pnn.pet.reminders.readiness import is_proactive_ready, is_schedule_runtime_ready

logger = logging.getLogger(__name__)

_NEGATIVE_RE = re.compile(r"(放鸽子|爽约|骗人|生气|讨厌你|不理你)")
_POSITIVE_RE = re.compile(r"(谢谢|辛苦|对不起.*原谅|最好了|喜欢你)")


class PresenceService:
    def __init__(self, session_key: str = "") -> None:
        self._session_key = session_key or "__default__"
        self._bundle: SessionPresenceBundle | None = None
        self._interrupt = InterruptTracker()
        self._emit_proactive: Callable[[str], None] | None = None
        self._on_unread: Callable[[int], None] | None = None
        self._config: PresenceConfig | None = None

    @property
    def session_key(self) -> str:
        return self._session_key

    @property
    def bundle(self) -> SessionPresenceBundle:
        if self._bundle is None:
            self._bundle = load_bundle(self._session_key)
        return self._bundle

    def _cfg(self) -> PresenceConfig:
        if self._config is None:
            self._config = load_presence_config()
        return self._config

    def reload_config(self) -> None:
        self._config = load_presence_config()
        cfg = self._cfg()
        self._interrupt = InterruptTracker(
            window_seconds=cfg.presence_interrupt_window_seconds,
            threshold=cfg.presence_interrupt_message_count,
        )

    def bind_session(self, session_key: str) -> None:
        self._session_key = session_key or "__default__"
        self._bundle = load_bundle(self._session_key)
        self.reload_config()

    def wire_dispatch(
        self,
        *,
        emit_proactive: Callable[[str], None] | None = None,
        on_unread: Callable[[int], None] | None = None,
    ) -> None:
        self._emit_proactive = emit_proactive
        self._on_unread = on_unread

    def save(self) -> None:
        save_bundle(self._session_key, self.bundle)

    def set_character_name(self, name: str) -> None:
        n = (name or "").strip()
        if n:
            self.bundle.state.character_name = n

    def add_timeline(
        self,
        event_type: TimelineEventType,
        summary: str,
        *,
        metadata: dict | None = None,
    ) -> None:
        self.bundle.timeline.append(
            TimelineEvent(
                event_type=event_type,
                summary=(summary or "")[:200],
                metadata=metadata or {},
            )
        )
        if len(self.bundle.timeline) > 200:
            self.bundle.timeline = self.bundle.timeline[-200:]

    def set_emotion(self, mood: str | EmotionMood, reason: str = "") -> None:
        try:
            em = EmotionMood(mood) if isinstance(mood, str) else mood
        except ValueError:
            em = EmotionMood.neutral
        st = self.bundle.state
        if st.emotion_mood != em or reason:
            st.emotion_mood = em
            st.emotion_reason = (reason or "")[:120]
            self.add_timeline(TimelineEventType.emotion, f"情绪→{em.value}: {reason or '—'}")

    def adjust_trust(self, delta: int) -> None:
        st = self.bundle.state
        st.trust_level = max(0, min(100, st.trust_level + int(delta)))

    def on_missed_appointment(self, title: str) -> None:
        self.adjust_trust(-6)
        self.set_emotion(EmotionMood.annoyed, f"用户错过了「{title}」")
        self.add_timeline(TimelineEventType.appointment, f"错过约定：{title}")

    def mark_proactive_dispatched(self) -> None:
        """主动搭话已真正送入 controller（非仅排队）。"""
        self.bundle.state.last_proactive_at = datetime.now()
        self.save()

    def _dispatch_trigger(self, kind: str, *, extra: str = "", mark_unread: bool = True) -> bool:
        if not self._cfg().presence_enabled:
            return False
        if not is_schedule_runtime_ready():
            return False
        if self._emit_proactive is None:
            return False

        text = build_presence_trigger(kind, self.bundle, extra=extra)
        try:
            dispatched = bool(self._emit_proactive(text))
        except Exception:
            logger.exception("主动对话派发失败")
            return False
        if not dispatched:
            logger.debug("主动对话未派发（忙碌或尚未就绪）: %s", kind)
            return False

        now = datetime.now()
        st = self.bundle.state
        if mark_unread and not st.window_focused:
            st.unread_proactive_count += 1
            if self._on_unread:
                try:
                    self._on_unread(st.unread_proactive_count)
                except Exception:
                    logger.exception("未读回调失败")
        self.save()
        return True

    def clear_unread(self) -> None:
        st = self.bundle.state
        if st.unread_proactive_count:
            st.unread_proactive_count = 0
            self.save()
            if self._on_unread:
                try:
                    self._on_unread(0)
                except Exception:
                    pass

    def on_startup(self) -> bool:
        now = datetime.now()
        st = self.bundle.state
        prev = st.last_session_seen_at
        st.last_session_seen_at = now
        st.last_user_activity_at = now
        self.save()

        if prev is None:
            return False
        if (now - prev).total_seconds() < 1800:
            return False
        self.add_timeline(
            TimelineEventType.absence,
            f"用户回归（分别 {int((now - prev).total_seconds() // 3600)}h+）",
        )
        return self._dispatch_trigger("absence_return")

    def on_user_message(self, text: str) -> str:
        now = datetime.now()
        st = self.bundle.state
        st.last_user_activity_at = now
        self.clear_unread()

        body = text or ""
        if _NEGATIVE_RE.search(body):
            self.set_emotion(EmotionMood.annoyed, "对话中出现负面冲突")
        elif _POSITIVE_RE.search(body):
            self.set_emotion(EmotionMood.happy, "用户表达感谢/和解")

        fulfilled = apply_fulfillment_effects(self, self._session_key, body)

        prefix = ""
        if fulfilled:
            prefix = build_presence_trigger("fulfillment", self.bundle)

        if self._interrupt.record_and_should_interrupt(now):
            st.last_interrupt_at = now
            interrupt = build_presence_trigger("interrupt", self.bundle)
            prefix = f"{prefix}\n\n{interrupt}".strip() if prefix else interrupt
            self.add_timeline(TimelineEventType.idle, "用户连发消息，触发抢话提示")

        self.save()
        return prefix

    def on_assistant_reply(self, user_text: str, assistant_text: str, *, character_name: str = "") -> None:
        sync_profile_from_turn(
            self,
            user_text=user_text,
            assistant_text=assistant_text,
            character_name=character_name,
        )

    def on_window_focus(self, focused: bool) -> None:
        st = self.bundle.state
        now = datetime.now()
        st.window_focused = focused
        if focused:
            st.last_window_focus_at = now
            self.clear_unread()
            if st.last_window_blur_at and (now - st.last_window_blur_at).total_seconds() > 120:
                self._dispatch_trigger("return_focus", mark_unread=False)
            self.add_timeline(TimelineEventType.focus, "窗口回到前台")
        else:
            st.last_window_blur_at = now
            self.add_timeline(TimelineEventType.focus, "窗口离开/最小化")
        self.save()

    def tick_idle(self) -> bool:
        cfg = load_presence_config()
        if not cfg.presence_enabled or not is_schedule_runtime_ready():
            return False
        if not is_proactive_ready():
            return False

        st = self.bundle.state
        now = datetime.now()
        last = st.last_user_activity_at or st.last_session_seen_at
        if last is None:
            return False

        idle_sec = max(60, int(cfg.presence_idle_seconds))
        afk_sec = max(idle_sec, int(cfg.presence_afk_seconds))
        prob = max(0.0, min(1.0, float(cfg.presence_idle_probability)))
        elapsed = (now - last).total_seconds()

        if elapsed < idle_sec:
            return False
        if st.last_proactive_at and (now - st.last_proactive_at).total_seconds() < idle_sec:
            return False

        logger.debug(
            "空闲检测：已空闲 %.0fs / 阈值 %ss，概率 %.2f",
            elapsed,
            idle_sec,
            prob,
        )

        if elapsed >= afk_sec:
            if random.random() > prob * 0.5:
                return False
            self.add_timeline(TimelineEventType.idle, "长时间挂机，轻声搭话")
            return self._dispatch_trigger("afk")

        if random.random() > prob:
            return False
        st.idle_nudge_count += 1
        self.add_timeline(TimelineEventType.idle, f"空闲搭话 #{st.idle_nudge_count}")
        logger.info("触发空闲搭话 #%s（空闲 %.0fs）", st.idle_nudge_count, elapsed)
        return self._dispatch_trigger("idle")


_singleton: PresenceService | None = None


def get_presence_service() -> PresenceService:
    global _singleton
    if _singleton is None:
        _singleton = PresenceService()
    return _singleton
