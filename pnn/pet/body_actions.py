"""按模型 cdi3 能力生成 sway 等整身感动作。"""

from __future__ import annotations

from pnn.pet.model_params import pick_body_sway_param

Keyframe = tuple[int, str, float]

# 躯干摇摆：振幅逐次衰减，时间间隔略不对称（转向稍慢、回中稍快）
_BODY_SWAY_PROFILE: list[tuple[int, float]] = [
    (0, 0.0),
    (280, -1.0),
    (560, 0.86),
    (820, -0.56),
    (1040, 0.34),
    (1240, -0.15),
    (1420, 0.06),
    (1620, 0.0),
]

# 头部略提前、幅度更小，避免与躯干完全同步显得「整坨在晃」
_HEAD_SWAY_PROFILE: list[tuple[int, float]] = [
    (0, 0.0),
    (250, -1.0),
    (530, 0.88),
    (790, -0.58),
    (1010, 0.36),
    (1210, -0.16),
    (1390, 0.06),
    (1590, 0.0),
]

_BODY_AMP = 9.5
_HEAD_AMP = 4.0
_Z_LEAN = 3.2
_Y_BOB = 1.4


def _append(frames: list[Keyframe], t: int, params: dict[str, float]) -> None:
    for pid, val in params.items():
        if pid:
            frames.append((t, pid, float(val)))


def _apply_body_sway(
    frames: list[Keyframe],
    *,
    t: int,
    factor: float,
    body_x: str,
    body_y: str | None,
    body_z: str | None,
) -> None:
    bx = _BODY_AMP * factor
    params: dict[str, float] = {body_x: bx}
    if body_z:
        params[body_z] = factor * _Z_LEAN
    if body_y:
        params[body_y] = -abs(factor) * _Y_BOB
    _append(frames, t, params)


def build_sway_action(available: set[str], names: dict[str, str]) -> list[Keyframe]:
    """左右摇摆：躯干主导 + 头部略领先；裙/发随 ParamBodyAngle 物理链跟随。"""
    _ = names
    body_x = pick_body_sway_param(available) or "ParamBodyAngleX"
    head_x = "ParamAngleX" if "ParamAngleX" in available else None
    body_z = "ParamBodyAngleZ" if "ParamBodyAngleZ" in available else None
    body_y = "ParamBodyAngleY" if "ParamBodyAngleY" in available else None

    frames: list[Keyframe] = []
    for t, factor in _BODY_SWAY_PROFILE:
        _apply_body_sway(
            frames,
            t=t,
            factor=factor,
            body_x=body_x,
            body_y=body_y,
            body_z=body_z,
        )
    if head_x:
        for t, factor in _HEAD_SWAY_PROFILE:
            _append(frames, t, {head_x: _HEAD_AMP * factor})

    frames.sort(key=lambda x: (x[0], x[1]))
    return frames


def build_default_sway_keyframes() -> list[Keyframe]:
    """无 cdi3 时的默认 Param 名。"""
    available = {
        "ParamBodyAngleX",
        "ParamAngleX",
        "ParamBodyAngleZ",
        "ParamBodyAngleY",
    }
    return build_sway_action(available, {})


def build_adaptive_body_actions(
    available: set[str],
    names: dict[str, str],
) -> dict[str, list[Keyframe]]:
    if not available:
        return {}
    return {
        "sway": build_sway_action(available, names),
    }
