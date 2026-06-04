"""Live2D 参数关键帧动作：点头/摇头/歪头/鞠躬/惊讶。"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# 每个动作 = [(elapsed_ms, param_name, value), ...]
# 末尾自动回 0（各参数归位），不需要显式写最后一帧
ACTIONS: dict[str, list[tuple[int, str, float]]] = {
    "nod": [
        (0, "ParamAngleY", 0),
        (120, "ParamAngleY", 18),
        (280, "ParamAngleY", -10),
        (420, "ParamAngleY", 10),
        (560, "ParamAngleY", 0),
    ],
    "shake_head": [
        (0, "ParamAngleX", 0),
        (100, "ParamAngleX", -15),
        (250, "ParamAngleX", 13),
        (400, "ParamAngleX", -10),
        (530, "ParamAngleX", 6),
        (650, "ParamAngleX", 0),
    ],
    "tilt_head": [
        (0, "ParamAngleZ", 0),
        (150, "ParamAngleZ", 16),
        (350, "ParamAngleZ", -4),
        (500, "ParamAngleZ", 0),
    ],
    "bow": [
        (0, "ParamBodyAngleZ", 0),
        (250, "ParamBodyAngleZ", 15),
        (600, "ParamBodyAngleZ", 15),
        (800, "ParamBodyAngleZ", 0),
    ],
    "surprise": [
        (0, "ParamBodyAngleZ", 0),
        (80, "ParamBodyAngleZ", -9),
        (350, "ParamBodyAngleZ", -9),
        (550, "ParamBodyAngleZ", 0),
    ],
}

# 动作中文名，供 LLM 指令使用
ACTION_NAMES: list[tuple[str, str]] = [
    ("nod", "点头（肯定、同意时）"),
    ("shake_head", "摇头（否定、拒绝时）"),
    ("tilt_head", "歪头（疑惑、卖萌时）"),
    ("bow", "鞠躬（问候、道谢、道歉时）"),
    ("surprise", "惊讶（听到意外消息时）"),
]


class ActionPlayer:
    """在 Live2DWidget 的渲染循环中驱动关键帧动作。"""

    def __init__(self, set_param) -> None:
        self._set_param = set_param
        self._start = 0.0
        self._keyframes: list[tuple[int, str, float]] = []
        self._active = False

    def play(self, name: str) -> bool:
        frames = ACTIONS.get(name)
        if not frames:
            logger.warning("未知动作: %s", name)
            return False
        self._keyframes = frames
        self._start = time.time()
        self._active = True
        return True

    def is_active(self) -> bool:
        return self._active

    def active_param_set(self) -> set[str]:
        """返回当前动作正在控制的参数名集合（指针追踪/空闲动画需避让）。"""
        if not self._active:
            return set()
        return {p for _, p, _ in self._keyframes}

    def stop(self) -> None:
        self._active = False
        self._keyframes = []

    def tick(self) -> None:
        if not self._active or not self._keyframes:
            return
        elapsed = (time.time() - self._start) * 1000
        total = self._keyframes[-1][0]
        if elapsed >= total:
            self._finish()
            return

        # 线性插值
        for i in range(len(self._keyframes) - 1):
            t0, p0, v0 = self._keyframes[i]
            t1, p1, v1 = self._keyframes[i + 1]
            if p0 != p1:
                continue
            if t0 <= elapsed <= t1:
                ratio = (elapsed - t0) / (t1 - t0) if t1 > t0 else 0
                self._set_param(p0, v0 + (v1 - v0) * ratio)

    def _finish(self) -> None:
        # 写入最后一帧值
        _, last_param, last_val = self._keyframes[-1]
        try:
            self._set_param(last_param, last_val)
        except Exception:
            pass
        self._active = False
        self._keyframes = []
