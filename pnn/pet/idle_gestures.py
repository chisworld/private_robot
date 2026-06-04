"""待机随机肢体动作：前倾、上身左右晃、胸口晃等（按模型参数自动启用）。"""

from __future__ import annotations

from pnn.pet.model_params import chest_parameter_ids, pick_body_sway_param, pick_lean_forward_param

Keyframe = tuple[int, str, float]

# 供 LLM 触发的固定动作（见 actions.ACTIONS）
LLM_ACTION_NAMES = frozenset({"nod", "shake_head", "tilt_head", "bow", "surprise"})


def _scale_frames(frames: list[Keyframe], amplitude: float) -> list[Keyframe]:
    amp = max(0.0, min(3.0, float(amplitude)))
    if abs(amp - 1.0) < 0.02:
        return list(frames)
    return [(t, p, v * amp) for t, p, v in frames]


def build_lean_forward(param: str) -> list[Keyframe]:
    return [
        (0, param, 0.0),
        (220, param, 14.0),
        (520, param, 14.0),
        (780, param, 0.0),
    ]


def build_body_sway(param: str) -> list[Keyframe]:
    return [
        (0, param, 0.0),
        (140, param, -13.0),
        (300, param, 14.0),
        (460, param, -11.0),
        (600, param, 9.0),
        (760, param, 0.0),
    ]


def build_chest_bounce(param: str) -> list[Keyframe]:
    return [
        (0, param, 0.0),
        (100, param, 0.42),
        (220, param, -0.12),
        (340, param, 0.38),
        (460, param, -0.08),
        (580, param, 0.28),
        (720, param, 0.0),
    ]


def build_upper_quiver(param_x: str, param_y: str | None = None) -> list[Keyframe]:
    frames: list[Keyframe] = [
        (0, param_x, 0.0),
        (120, param_x, 6.0),
        (240, param_x, -5.5),
        (360, param_x, 4.5),
        (480, param_x, 0.0),
    ]
    if param_y:
        frames.extend(
            [
                (0, param_y, 0.0),
                (160, param_y, 3.0),
                (320, param_y, -2.5),
                (480, param_y, 0.0),
            ]
        )
        frames.sort(key=lambda x: x[0])
    return frames


def build_idle_gesture_pool(available: set[str]) -> tuple[list[str], dict[str, list[Keyframe]]]:
    """返回 (可随机播放的动作名列表, 动作名→关键帧)。"""
    pool: list[str] = []
    gestures: dict[str, list[Keyframe]] = {}

    lean = pick_lean_forward_param(available)
    if lean:
        pool.append("lean_forward")
        gestures["lean_forward"] = build_lean_forward(lean)

    sway = pick_body_sway_param(available)
    if sway:
        pool.append("body_sway")
        gestures["body_sway"] = build_body_sway(sway)

    chest = chest_parameter_ids(available)
    if chest:
        pool.append("chest_bounce")
        gestures["chest_bounce"] = build_chest_bounce(chest[0])

    if "ParamBodyAngleX" in available and "ParamBodyAngleY" in available:
        pool.append("upper_quiver")
        gestures["upper_quiver"] = build_upper_quiver(
            "ParamBodyAngleX", "ParamBodyAngleY"
        )
    elif sway and sway != "ParamBodyAngleX":
        pool.append("upper_quiver")
        gestures["upper_quiver"] = build_upper_quiver(sway)

    return pool, gestures


def scale_gesture_frames(
    gestures: dict[str, list[Keyframe]], amplitude: float
) -> dict[str, list[Keyframe]]:
    return {name: _scale_frames(frames, amplitude) for name, frames in gestures.items()}
