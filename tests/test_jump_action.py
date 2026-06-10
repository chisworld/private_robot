"""sway 等模型自适应动作。"""
from pathlib import Path

from pnn.pet.actions import ACTIONS, resolve_action_min_duration_ms
from pnn.pet.body_actions import build_sway_action
from pnn.pet.model_params import discover_parameter_ids, discover_parameter_names

RISONA_DIR = Path("live2d") / "里想奈"


def test_jump_action_removed():
    assert "jump" not in ACTIONS


def test_sway_includes_head_and_body():
    frames = ACTIONS["sway"]
    params = {p for _, p, _ in frames}
    assert "ParamBodyAngleX" in params
    assert "ParamAngleX" in params
    assert frames[-1][0] >= 1500
    assert resolve_action_min_duration_ms("sway") is None


def test_risona_sway_body_and_head_only():
    if not RISONA_DIR.is_dir():
        return
    available = discover_parameter_ids(RISONA_DIR)
    names = discover_parameter_names(RISONA_DIR)
    frames = build_sway_action(available, names)
    params = {p for _, p, _ in frames}
    assert "ParamBodyAngleX" in params
    assert "ParamAngleX" in params
    assert "Param35" not in params
