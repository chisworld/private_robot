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
    # 坐下再站起：身体前倾并保持，再缓慢起身
    "sit": [
        (0, "ParamBodyAngleZ", 0),
        (0, "ParamBodyAngleY", 0),
        (420, "ParamBodyAngleZ", 20),
        (420, "ParamBodyAngleY", -10),
        (1400, "ParamBodyAngleZ", 20),
        (1400, "ParamBodyAngleY", -10),
        (1900, "ParamBodyAngleZ", 8),
        (1900, "ParamBodyAngleY", -4),
        (2300, "ParamBodyAngleZ", 0),
        (2300, "ParamBodyAngleY", 0),
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
    # 左右摇摆（模型加载后 body_actions 会覆盖为自适应曲线）
    "sway": [],  # 占位；模块末尾填充默认曲线
}

try:
    from pnn.pet.body_actions import build_default_sway_keyframes

    ACTIONS["sway"] = build_default_sway_keyframes()
except Exception:
    ACTIONS["sway"] = [
        (0, "ParamBodyAngleX", 0.0),
        (1620, "ParamBodyAngleX", 0.0),
    ]

# 动作中文名，供 LLM 指令使用
# 无语音绑定时，动作至少播放这么久（毫秒），避免「闪一下」就结束
DEFAULT_ACTION_MIN_MS = 1600
# 按动作覆盖最小时长；0 表示不拉伸（保持原生节奏）
ACTION_MIN_DURATION_MS: dict[str, int] = {
    "sway": 0,
    "surprise": 900,
    "nod": 1100,
    "shake_head": 1100,
    "tilt_head": 1000,
    "sit": 2800,
}
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


def resolve_action_min_duration_ms(
    name: str,
    *,
    override: int | None = None,
) -> int | None:
    """解析动作最短时长；None 表示不拉伸时间轴。"""
    if override is not None:
        return None if int(override) <= 0 else int(override)
    raw = ACTION_MIN_DURATION_MS.get(name, DEFAULT_ACTION_MIN_MS)
    return None if int(raw) <= 0 else int(raw)


def _smoothstep(ratio: float) -> float:
    ratio = max(0.0, min(1.0, float(ratio)))
    return ratio * ratio * (3.0 - 2.0 * ratio)


def speech_action_min_duration_ms(audio_duration_sec: float) -> int:
    """根据当前句语音时长计算动作最短持续时间。"""
    dur_ms = max(0.0, float(audio_duration_sec)) * 1000.0
    if dur_ms <= 0:
        return SPEECH_ACTION_MIN_MS
    target = int(dur_ms * SPEECH_ACTION_AUDIO_RATIO)
    return int(max(SPEECH_ACTION_MIN_MS, min(target, SPEECH_ACTION_MAX_MS)))


# 整身/躯干类（ParamBodyAngle*）
BODY_ACTION_NAMES: tuple[str, ...] = (
    "sway",
    "bow",
    "deep_bow",
    "stretch",
    "surprise",
    "sit",
)

#  primarily 头部（ParamAngle*）
HEAD_ACTION_NAMES: tuple[str, ...] = (
    "nod",
    "shake_head",
    "tilt_head",
)

ACTION_NAMES: list[tuple[str, str]] = [
    ("nod", "点头（肯定、同意时）"),
    ("shake_head", "摇头（否定、拒绝时）"),
    ("tilt_head", "歪头（疑惑、卖萌时）"),
    ("bow", "鞠躬（问候、道谢、道歉时）"),
    ("deep_bow", "深鞠躬（道歉、郑重问候时）"),
    ("surprise", "惊讶（听到意外消息时）"),
    ("sit", "坐下又站起（累了、休息时）"),
    ("stretch", "伸懒腰（刚睡醒、疲惫时）"),
    ("sway", "左右摇摆（开心哼歌时）"),
]

_ACTION_ALIASES: dict[str, str] = {}
for _id, _desc in ACTION_NAMES:
    _ACTION_ALIASES[_id] = _id
    _ACTION_ALIASES[_id.replace("_", " ")] = _id
    _ACTION_ALIASES[_id.replace("_", "")] = _id
_ACTION_ALIASES.update(
    {
        "晃": "sway",
        "晃身": "sway",
        "摇摆": "sway",
        "左右晃": "sway",
        "鞠躬": "bow",
        "深鞠躬": "deep_bow",
        "低头": "bow",
        "伸懒腰": "stretch",
        "惊讶": "surprise",
        "坐": "sit",
        "坐下": "sit",
        "点头": "nod",
        "摇头": "shake_head",
        "歪头": "tilt_head",
    }
)


def resolve_action_name(raw: str | None) -> str | None:
    """将 LLM/中文别名解析为 ACTIONS 键名。"""
    key = (raw or "").strip()
    if not key:
        return None
    if key in ACTIONS:
        return key
    low = key.lower()
    if low in ACTIONS:
        return low
    if key in _ACTION_ALIASES:
        return _ACTION_ALIASES[key]
    if low in _ACTION_ALIASES:
        return _ACTION_ALIASES[low]
    return None


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
        min_duration_ms: int | None = None,
    ) -> bool:
        raw = self._extra.get(name) or ACTIONS.get(name)
        if not raw:
            logger.warning("未知动作: %s", name)
            return False
        duration = resolve_action_min_duration_ms(name, override=min_duration_ms)
        frames = list(raw)
        amp = max(0.0, min(3.0, float(amplitude)))
        if abs(amp - 1.0) >= 0.02:
            frames = [(t, p, v * amp) for t, p, v in frames]
        frames = stretch_action_frames(frames, duration)
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

    def _elapsed_ms(self) -> float:
        return (time.time() - self._start) * 1000

    def _apply_at(self, elapsed: float) -> None:
        """按时间轴插值并写入 Live2D 参数。"""
        if not self._keyframes:
            return
        by_param: dict[str, list[tuple[int, float]]] = {}
        for t, param, val in self._keyframes:
            by_param.setdefault(param, []).append((t, val))
        for param, samples in by_param.items():
            samples.sort(key=lambda x: x[0])
            applied = False
            for i in range(len(samples) - 1):
                t0, v0 = samples[i]
                t1, v1 = samples[i + 1]
                if t0 <= elapsed <= t1:
                    ratio = (elapsed - t0) / (t1 - t0) if t1 > t0 else 0.0
                    eased = _smoothstep(ratio)
                    self._set_param(param, v0 + (v1 - v0) * eased)
                    applied = True
                    break
            if not applied and samples:
                _, last_val = samples[-1]
                self._set_param(param, last_val)

    def reapply(self) -> None:
        """绘制前再次写入当前帧（physics Update 之后），避免动作被物理覆盖。"""
        if self._active and self._keyframes:
            self._apply_at(self._elapsed_ms())

    def tick(self) -> None:
        if not self._active or not self._keyframes:
            return
        elapsed = self._elapsed_ms()
        total = self._keyframes[-1][0]
        if elapsed >= total:
            self._finish()
            return
        self._apply_at(elapsed)

    def _finish(self) -> None:
        self._apply_at(self._keyframes[-1][0])
        self._active = False
        self._keyframes = []
