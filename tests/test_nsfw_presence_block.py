"""NSFW 模式下禁用 presence 主动搭话。"""

from __future__ import annotations

from pnn.llm.config_store import LlmConfig
from pnn.llm.routing import nsfw_blocks_presence_proactive


def test_nsfw_blocks_idle_and_greet():
    cfg = LlmConfig(nsfw_enabled=True)
    assert nsfw_blocks_presence_proactive("idle")
    assert nsfw_blocks_presence_proactive("afk")
    assert nsfw_blocks_presence_proactive("window_greet")
    assert not nsfw_blocks_presence_proactive("pomodoro_focus_end")


def test_nsfw_off_allows_idle(monkeypatch):
    cfg = LlmConfig(nsfw_enabled=False)
    monkeypatch.setattr("pnn.llm.config_store.load_llm_config", lambda: cfg)
    assert not nsfw_blocks_presence_proactive("idle")


def test_dispatch_skips_idle_when_nsfw(monkeypatch):
    from pnn.pet.presence.service import PresenceService

    cfg = LlmConfig(nsfw_enabled=True)
    monkeypatch.setattr("pnn.llm.config_store.load_llm_config", lambda: cfg)
    monkeypatch.setattr(
        "pnn.pet.presence.service.is_schedule_runtime_ready",
        lambda: True,
    )

    svc = PresenceService()
    svc.bind_session("test")
    called: list[str] = []

    def _emit(text: str) -> bool:
        called.append(text)
        return True

    svc.wire_dispatch(emit_proactive=_emit)
    assert not svc._dispatch_trigger("idle")
    assert called == []
