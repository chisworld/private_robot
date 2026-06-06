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
    "deep_bow": [
        (0, "ParamBodyAngleZ", 0),
        (350, "ParamBodyAngleZ", 28),
        (1000, "ParamBodyAngleZ", 28),
        (1400, "ParamBodyAngleZ", 0),
    ],
    "surprise": [
        (0, "ParamBodyAngleZ", 0),
        (80, "ParamBodyAngleZ", -9),
        (350, "ParamBodyAngleZ", -9),
        (550, "ParamBodyAngleZ", 0),
    ],
    # 跳起来：蹲→弹起→落地（使用 BodyAngleY = 身体上下位移）
    "jump": [
        (0, "ParamBodyAngleY", 0),
        (180, "ParamBodyAngleY", -8),
        (300, "ParamBodyAngleY", 15),
        (420, "ParamBodyAngleY", 8),
        (520, "ParamBodyAngleY", -3),
        (620, "ParamBodyAngleY", 2),
        (720, "ParamBodyAngleY", 0),
    ],
    # 坐下去再站起来
    "sit": [
        (0, "ParamBodyAngleY", 0),
        (400, "ParamBodyAngleY", -12),
        (1800, "ParamBodyAngleY", -12),
        (2200, "ParamBodyAngleY", 0),
    ],
    # 伸懒腰：身体后仰 + 轻微左右晃
    "stretch": [
        (0, "ParamBodyAngleZ", 0),
        (250, "ParamBodyAngleZ", -10),
        (600, "ParamBodyAngleZ", -10),
        (800, "ParamBodyAngleZ", 5),
        (1000, "ParamBodyAngleZ", -5),
        (1200, "ParamBodyAngleZ", 0),
    ],
    # 左右摇摆（开心时）
    "sway": [
        (0, "ParamBodyAngleX", 0),
        (200, "ParamBodyAngleX", -10),
        (500, "ParamBodyAngleX", 10),
        (800, "ParamBodyAngleX", -6),
        (1100, "ParamBodyAngleX", 6),
        (1400, "ParamBodyAngleX", 0),
    ],
}

# 动作中文名，供 LLM 指令使用
# 无语音绑定时，动作至少播放这么久（毫秒），避免「闪一下」就结束
DEFAULT_ACTION_MIN_MS = 1600
# 与 TTS 同步时：动作时长下限、相对语音时长比例、上限
SPEECH_ACTION_MIN_MS = 1800
SPEECH_ACTION_AUDIO_RATIO = 0.88
SPEECH_ACTION_MAX_MS = 8000


def stretch_action_frames(
    frames: list[tuple[int, str, float]],
    min_duration_ms: int | None,
) -> list[tuple[int, str, float]]:
    """按比例拉长时间轴，使动作至少持续 min_duration_ms。"""
    if not frames or not min_duration_ms or min_duration_ms <= 0:
        return list(frames)
    total = frames[-1][0]
    if total <= 0 or total >= min_duration_ms:
        return list(frames)
    scale = min_duration_ms / total
    return [(max(0, int(round(t * scale))), p, v) for t, p, v in frames]


def speech_action_min_duration_ms(audio_duration_sec: float) -> int:
    """根据当前句语音时长计算动作最短持续时间。"""
    dur_ms = max(0.0, float(audio_duration_sec)) * 1000.0
    if dur_ms <= 0:
        return SPEECH_ACTION_MIN_MS
    target = int(dur_ms * SPEECH_ACTION_AUDIO_RATIO)
    return int(max(SPEECH_ACTION_MIN_MS, min(target, SPEECH_ACTION_MAX_MS)))


ACTION_NAMES: list[tuple[str, str]] = [
    ("nod", "点头（肯定、同意时）"),
    ("shake_head", "摇头（否定、拒绝时）"),
    ("tilt_head", "歪头（疑惑、卖萌时）"),
    ("bow", "鞠躬（问候、道谢、道歉时）"),
    ("deep_bow", "深鞠躬（道歉、郑重问候时）"),
    ("surprise", "惊讶（听到意外消息时）"),
    ("jump", "跳起来（开心、兴奋时）"),
    ("sit", "坐下又站起（累了、休息时）"),
    ("stretch", "伸懒腰（刚睡醒、疲惫时）"),
    ("sway", "左右摇摆（开心哼歌时）"),
]


class ActionPlayer:
    """在 Live2DWidget 的渲染循环中驱动关键帧动作。"""

    def __init__(self, set_param) -> None:
        self._set_param = set_param
        self._start = 0.0
        self._keyframes: list[tuple[int, str, float]] = []
        self._active = False
        self._extra: dict[str, list[tuple[int, str, float]]] = {}

    def register_actions(self, extra: dict[str, list[tuple[int, str, float]]]) -> None:
        self._extra = dict(extra)

    def play(
        self,
        name: str,
        *,
        amplitude: float = 1.0,
        min_duration_ms: int | None = DEFAULT_ACTION_MIN_MS,
    ) -> bool:
        raw = self._extra.get(name) or ACTIONS.get(name)
        if not raw:
            logger.warning("未知动作: %s", name)
            return False
        frames = list(raw)
        amp = max(0.0, min(3.0, float(amplitude)))
        if abs(amp - 1.0) >= 0.02:
            frames = [(t, p, v * amp) for t, p, v in frames]
        frames = stretch_action_frames(frames, min_duration_ms)
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

        # 按参数分别插值（多参数动作如晃身/胸口）
        by_param: dict[str, list[tuple[int, float]]] = {}
        for t, param, val in self._keyframes:
            by_param.setdefault(param, []).append((t, val))
        for param, samples in by_param.items():
            samples.sort(key=lambda x: x[0])
            for i in range(len(samples) - 1):
                t0, v0 = samples[i]
                t1, v1 = samples[i + 1]
                if t0 <= elapsed <= t1:
                    ratio = (elapsed - t0) / (t1 - t0) if t1 > t0 else 0.0
                    self._set_param(param, v0 + (v1 - v0) * ratio)
                    break

    def _finish(self) -> None:
        # 写入最后一帧值
        _, last_param, last_val = self._keyframes[-1]
        try:
            self._set_param(last_param, last_val)
        except Exception:
            pass
        self._active = False
        self._keyframes = []
