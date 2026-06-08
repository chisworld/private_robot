"""整身/头部动作解析。"""

from __future__ import annotations

from pnn.pet.actions import BODY_ACTION_NAMES, resolve_action_name


def test_resolve_action_aliases():
    assert resolve_action_name("jump") == "jump"
    assert resolve_action_name("跳") == "jump"
    assert resolve_action_name("鞠躬") == "bow"
    assert resolve_action_name("sway") == "sway"
    assert resolve_action_name("unknown") is None


def test_body_action_names_include_core():
    assert "jump" in BODY_ACTION_NAMES
    assert "sway" in BODY_ACTION_NAMES
    assert "bow" in BODY_ACTION_NAMES


def test_tap_reaction_prefers_body_action_when_random_low(monkeypatch):
    from pnn.pet.live2d_widget import Live2DWidget

    w = Live2DWidget.__new__(Live2DWidget)
    w._model = object()
    w._ready = True
    w._playing_speech = False
    w._performance_hold = False
    w._motion_active = False
    w._idle_amplitude = 1.0
    w._idle_gesture_pool = []
    w._action_player = type("P", (), {"is_active": lambda self: False, "play": lambda self, *a, **k: True})()
    monkeypatch.setattr("random.random", lambda: 0.1)
    monkeypatch.setattr(w, "_pick_tap_body_action", lambda: "jump")
    called: list[str] = []

    def fake_expr():
        called.append("expr")

    monkeypatch.setattr(w, "_pick_tap_expression", fake_expr)
    w.play_tap_reaction()
    assert called == []
