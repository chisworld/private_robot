"""整身/头部动作解析。"""

from __future__ import annotations

from pnn.pet.actions import BODY_ACTION_NAMES, resolve_action_name


def test_resolve_action_aliases():
    assert resolve_action_name("bow") == "bow"
    assert resolve_action_name("鞠躬") == "bow"
    assert resolve_action_name("sway") == "sway"
    assert resolve_action_name("跳") is None
    assert resolve_action_name("jump") is None
    assert resolve_action_name("unknown") is None


def test_body_action_names_include_core():
    assert "jump" not in BODY_ACTION_NAMES
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
    w._idle_expr_release_timer = type("T", (), {"stop": lambda self: None, "start": lambda self, *a: None})()
    w._performance_expr_timer = type("T", (), {"stop": lambda self: None})()
    w._expr_motions = {}
    w._tap_body_picker = type("P", (), {"pick": lambda self: "sway"})()
    w._tap_action_picker = type("P", (), {"pick": lambda self: ""})()
    w._tap_expr_picker = type("P", (), {"pick": lambda self: ""})()
    w._action_player = type("P", (), {"is_active": lambda self: False, "play": lambda self, *a, **k: True})()
    monkeypatch.setattr("random.random", lambda: 0.1)
    monkeypatch.setattr(w, "_pick_tap_body_action", lambda: "sway")
    monkeypatch.setattr(w, "_pick_tap_expression", lambda: "")
    monkeypatch.setattr(w, "_play_tap_body_action", lambda name: True)
    w.play_tap_reaction()
