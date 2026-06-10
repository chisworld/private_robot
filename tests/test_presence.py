"""在场感 / 日程 / 气泡三通道 单元测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from pnn.pet.presence.config import PresenceConfig, load_presence_config, save_presence_config
from pnn.pet.presence.interrupt import InterruptTracker
from pnn.pet.presence.models import EmotionMood
from pnn.pet.presence.monitor import effective_poll_seconds
from pnn.pet.presence.service import PresenceService
from pnn.pet.presence.store import load_bundle, save_bundle
from pnn.pet.presence.triggers import build_presence_trigger
from pnn.pet.reminders.manager import ReminderManager, get_reminder_manager, session_key_from_character
from pnn.pet.reminders.models import ReminderStatus
from pnn.pet.reply_text import bubble_text_for_reply


def test_session_key_from_character():
    assert session_key_from_character("14chan") == "character:14chan"
    assert session_key_from_character("") == "__default__"


def test_is_api_recovering_after_recover():
    from pnn.pet import api_guard

    api_guard._last_recover_at = 0.0
    assert api_guard.is_api_recovering(within_seconds=30.0) is False
    api_guard._last_recover_at = __import__("time").monotonic()
    assert api_guard.is_api_recovering(within_seconds=30.0) is True


def test_is_proactive_ready_imports_api_guard(monkeypatch):
    """回归：is_api_recovering 缺失会导致主动搭话永远 False。"""
    from pnn.pet import api_guard
    from pnn.pet.reminders import readiness

    api_guard._last_recover_at = 0.0
    readiness.mark_pet_boot()
    monkeypatch.setattr(readiness, "boot_elapsed_seconds", lambda: 120.0)
    monkeypatch.setattr(
        "pnn.pet.api_guard.is_api_responsive",
        lambda **kw: True,
    )
    monkeypatch.setattr(
        "pnn.pet.reminders.readiness._llm_configured",
        lambda: True,
    )
    assert readiness.is_proactive_ready() is True


def test_effective_poll_scales_with_idle_interval():
    cfg = PresenceConfig(presence_idle_seconds=120, presence_poll_seconds=60)
    assert effective_poll_seconds(cfg) == 60
    cfg_short = PresenceConfig(presence_idle_seconds=60, presence_poll_seconds=45)
    assert effective_poll_seconds(cfg_short) == 30


def test_presence_config_roundtrip(isolated_presence_data, tmp_path):
    cfg = PresenceConfig(
        presence_idle_seconds=300,
        presence_idle_probability=0.8,
        presence_poll_seconds=45,
        presence_weather_city="上海",
    )
    save_presence_config(cfg)
    loaded = load_presence_config()
    assert loaded.presence_idle_seconds == 300
    assert loaded.presence_idle_probability == 0.8
    assert loaded.presence_poll_seconds == 45
    assert loaded.presence_weather_city == "上海"


def test_presence_spinbox_interpret_text():
    """保存前 interpretText 可确保数字框文本与 value() 一致。"""
    from PySide6.QtWidgets import QApplication, QSpinBox

    app = QApplication.instance() or QApplication([])
    idle = QSpinBox()
    idle.setRange(1, 180)
    idle.setValue(5)
    idle.lineEdit().setText("10")
    idle.interpretText()
    assert idle.value() == 10


def test_bundle_persist(isolated_presence_data):
    sk = "character:test"
    bundle = load_bundle(sk)
    bundle.state.trust_level = 77
    bundle.state.emotion_mood = EmotionMood.happy
    save_bundle(sk, bundle)

    again = load_bundle(sk)
    assert again.state.trust_level == 77
    assert again.state.emotion_mood == EmotionMood.happy


def test_build_presence_trigger_contains_system_marker(isolated_presence_data):
    svc = PresenceService("character:test")
    svc.bind_session("character:test")
    text = build_presence_trigger("idle", svc.bundle)
    assert "[系统提醒" in text
    assert "不要复读本段系统文本" in text


def test_idle_trigger_uses_recent_chat_not_absence_return(isolated_presence_data):
    svc = PresenceService("character:test")
    svc.bind_session("character:test")
    svc.bundle.state.last_session_seen_at = datetime.now() - timedelta(hours=5)
    svc.bundle.state.last_user_message = "走吧，一起洗澡去，我给你搓背"
    svc.bundle.state.last_assistant_message = "哥哥要帮我搓背吗…那好吧。"
    text = build_presence_trigger("idle", svc.bundle)
    assert "近期对话" in text
    assert "洗澡" in text
    assert "当前情境" in text
    assert "用户最后一句话" in text
    assert "用户已有" not in text
    assert "用户离开了约" not in text


def test_topic_avoidance_after_meal_chat(isolated_presence_data, tmp_path, monkeypatch):
    from pnn.pet.presence.conversation_context import build_topic_avoidance_hint
    from pnn.pet.presence.daily_log import append_daily_turn

    sk = "character:meal"
    append_daily_turn(sk, "嗯，我们吃饭吧", "好，菜都准备好了。")
    append_daily_turn(sk, "都有什么菜啊", "红烧肉、韭菜炒蛋和蛋汤。")
    append_daily_turn(sk, "帮我打开鸣潮", "登记好像还没弄好。")

    svc = PresenceService(sk)
    svc.bind_session(sk)
    hint = build_topic_avoidance_hint(svc.bundle, sk)
    assert "吃饭" in hint
    assert "勿再" in hint

    text = build_presence_trigger("idle", svc.bundle, session_key=sk)
    assert "话题续接" in text
    assert "勿再泛泛追问" in text


def test_silence_hint_quotes_last_user_line():
    from pnn.pet.presence.conversation_context import build_silence_scenario_hint
    from pnn.pet.presence.models import SessionPresenceBundle, SessionPresenceState

    bundle = SessionPresenceBundle(
        state=SessionPresenceState(
            last_user_message="一起洗澡去",
            last_assistant_message="好吧。",
            last_user_activity_at=datetime.now() - timedelta(minutes=8),
        )
    )
    hint = build_silence_scenario_hint(bundle)
    assert "一起洗澡去" in hint
    assert "当前情境" in hint


def test_on_user_message_no_fulfillment_from_chat(isolated_presence_data):
    sk = session_key_from_character("test")
    mgr = get_reminder_manager()
    mgr.reload()
    now = datetime.now()
    mgr.create(
        session_key=sk,
        title="一起玩鸣潮",
        scheduled_start=now - timedelta(minutes=10),
        scheduled_end=now + timedelta(minutes=20),
    )
    svc = PresenceService(sk)
    svc.bind_session(sk)
    prefix = svc.on_user_message("我已经在和你一起玩鸣潮了")
    assert not prefix or "履约" not in prefix
    pending = mgr.list_for_session(sk, status=ReminderStatus.pending)
    assert len(pending) == 1


def test_interrupt_tracker(isolated_presence_data):
    tr = InterruptTracker(window_seconds=10, threshold=3, cooldown_seconds=1)
    now = datetime.now()
    assert tr.record_and_should_interrupt(now) is False
    assert tr.record_and_should_interrupt(now) is False
    assert tr.record_and_should_interrupt(now) is True


def test_tick_idle_respects_probability(isolated_presence_data, monkeypatch):
    cfg = PresenceConfig(
        presence_enabled=True,
        presence_idle_seconds=60,
        presence_idle_probability=0.0,
        presence_afk_seconds=7200,
    )
    monkeypatch.setattr(
        "pnn.pet.presence.service.load_presence_config", lambda: cfg
    )
    monkeypatch.setattr(
        "pnn.pet.presence.service.is_schedule_runtime_ready", lambda: True
    )
    monkeypatch.setattr(
        "pnn.pet.presence.service.is_proactive_ready", lambda **kw: True
    )

    svc = PresenceService("character:prob")
    svc.bind_session("character:prob")
    svc.reload_config()
    svc.arm_idle_monitor()
    svc.bundle.state.last_user_activity_at = datetime.now() - timedelta(minutes=5)
    calls: list[str] = []

    def _noop_emit(_text: str) -> bool:
        return True

    svc.wire_dispatch(emit_proactive=_noop_emit)

    assert svc.tick_idle() is False
    assert calls == []


def test_tick_idle_fires_when_due(isolated_presence_data, monkeypatch):
    cfg = PresenceConfig(
        presence_enabled=True,
        presence_idle_seconds=60,
        presence_idle_probability=1.0,
        presence_afk_seconds=7200,
    )
    monkeypatch.setattr(
        "pnn.pet.presence.service.load_presence_config", lambda: cfg
    )
    monkeypatch.setattr(
        "pnn.pet.presence.service.is_schedule_runtime_ready", lambda: True
    )
    monkeypatch.setattr(
        "pnn.pet.presence.service.is_proactive_ready", lambda **kw: True
    )

    svc = PresenceService("character:due")
    svc.bind_session("character:due")
    svc.reload_config()
    svc.arm_idle_monitor()
    svc.bundle.state.last_user_activity_at = datetime.now() - timedelta(minutes=5)
    calls: list[str] = []

    def _capture_emit(text: str) -> bool:
        calls.append(text)
        return True

    svc.wire_dispatch(emit_proactive=_capture_emit)

    assert svc.tick_idle() is True
    assert len(calls) == 1
    assert "[系统提醒" in calls[0]


def test_reminder_create_and_complete(isolated_presence_data):
    sk = session_key_from_character("test")
    mgr = ReminderManager()
    start = datetime.now() - timedelta(minutes=5)
    r = mgr.create(
        session_key=sk,
        title="一起吃早饭",
        scheduled_start=start,
        scheduled_end=start + timedelta(hours=1),
    )
    assert r.status.value == "pending"
    done = mgr.mark_completed(r.id)
    assert done is not None
    assert done.status.value == "completed"


def test_bubble_strips_memory_meta_narration():
    raw = "根据记忆，你昨天说过要早起。那就早点休息吧！"
    bubble = bubble_text_for_reply(raw)
    assert bubble
    assert "根据记忆" not in bubble
    assert "休息" in bubble


def test_proactive_not_ready_during_boot_quiet(isolated_presence_data, monkeypatch):
    from pnn.pet.reminders import readiness as rd

    rd.mark_pet_boot()
    sent: list[str] = []

    class _Ctl:
        def is_busy(self):
            return False

        def send_proactive(self, t):
            sent.append(t)

    from pnn.pet.presence.runtime import PresenceRuntime

    rt = PresenceRuntime(_Ctl(), get_character_id=lambda: "test")
    rt._emit_proactive("[系统提醒] test")
    assert sent == []


def test_on_startup_skips_when_recent_chat(isolated_presence_data, monkeypatch):
    cfg = PresenceConfig(presence_enabled=True)
    monkeypatch.setattr("pnn.pet.presence.service.load_presence_config", lambda: cfg)
    monkeypatch.setattr(
        "pnn.pet.presence.service.is_schedule_runtime_ready", lambda: True
    )

    svc = PresenceService("character:resume")
    svc.bind_session("character:resume")
    svc.bundle.state.last_session_seen_at = datetime.now() - timedelta(hours=2)
    svc.bundle.state.last_user_message = "一起洗澡去"
    svc.bundle.state.last_assistant_message = "好吧…"
    svc.bundle.state.last_user_activity_at = datetime.now() - timedelta(minutes=20)

    assert svc.on_startup() is False


def test_try_session_resume_dispatches(isolated_presence_data, monkeypatch):
    cfg = PresenceConfig(presence_enabled=True)
    monkeypatch.setattr("pnn.pet.presence.service.load_presence_config", lambda: cfg)
    monkeypatch.setattr(
        "pnn.pet.presence.service.is_schedule_runtime_ready", lambda: True
    )

    svc = PresenceService("character:resume2")
    svc.bind_session("character:resume2")
    svc.bundle.state.last_user_message = "一起洗澡去"
    svc.bundle.state.last_user_activity_at = datetime.now() - timedelta(minutes=10)
    captured: list[str] = []

    def _emit(text: str) -> bool:
        captured.append(text)
        return True

    svc.wire_dispatch(emit_proactive=_emit)
    assert svc.try_session_resume() is True
    assert captured
    assert "session_resume" not in captured[0]
    assert "接续" in captured[0] or "近期对话" in captured[0]


def test_has_recent_conversation_from_state():
    from pnn.pet.presence.conversation_context import has_recent_conversation
    from pnn.pet.presence.models import SessionPresenceBundle, SessionPresenceState

    bundle = SessionPresenceBundle(
        state=SessionPresenceState(
            last_user_message="一起洗澡",
            last_user_activity_at=datetime.now() - timedelta(minutes=30),
        )
    )
    assert has_recent_conversation(bundle, "character:x") is True


def test_build_presence_trigger_session_resume_includes_chat(isolated_presence_data):
    svc = PresenceService("character:test")
    svc.bind_session("character:test")
    svc.bundle.state.last_user_message = "一起洗澡去"
    text = build_presence_trigger("session_resume", svc.bundle)
    assert "近期对话" in text
    assert "洗澡" in text
    assert "欢迎回家" in text  # instruction text mentions what NOT to do


def test_negative_emotion_on_conflict(isolated_presence_data):
    svc = PresenceService("character:mood")
    svc.bind_session("character:mood")
    svc.on_user_message("你放鸽子了，我讨厌你")
    assert svc.bundle.state.emotion_mood == EmotionMood.annoyed
