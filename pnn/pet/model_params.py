"""从 Live2D 模型目录读取 cdi3 参数 Id，用于按模型能力启用待机动作。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CHEST_HINTS = ("breast", "bust", "chest", "胸", "おっぱい", "乳")
_BODY_ANGLE_HINTS = ("bodyangle", "body_angle")


def discover_parameter_ids(model_dir: Path) -> set[str]:
    """合并模型目录下所有 *.cdi3.json 中的 Parameters[].Id。"""
    ids: set[str] = set()
    if not model_dir.is_dir():
        return ids
    for path in sorted(model_dir.glob("*.cdi3.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("跳过 cdi3 %s: %s", path.name, exc)
            continue
        for item in data.get("Parameters") or []:
            pid = str(item.get("Id") or "").strip()
            if pid:
                ids.add(pid)
    # 标准 Cubism 参数多数模型都有，即使 cdi3 未列出也允许尝试
    ids.update(
        {
            "ParamAngleX",
            "ParamAngleY",
            "ParamAngleZ",
            "ParamBodyAngleX",
            "ParamBodyAngleY",
            "ParamBodyAngleZ",
        }
    )
    return ids


def chest_parameter_ids(available: set[str]) -> list[str]:
    """优先 Y 轴（上下晃），其次 X；无胸口参数则返回空。"""
    hits = [
        pid
        for pid in sorted(available)
        if any(h in pid.lower() for h in _CHEST_HINTS)
    ]
    if not hits:
        return []

    def _rank(pid: str) -> tuple[int, str]:
        low = pid.lower()
        axis = 2
        if low.endswith("y"):
            axis = 0
        elif low.endswith("x"):
            axis = 1
        return (axis, pid)

    return sorted(hits, key=_rank)[:2]


def pick_body_sway_param(available: set[str]) -> str | None:
    if "ParamBodyAngleX" in available:
        return "ParamBodyAngleX"
    if "ParamAngleX" in available:
        return "ParamAngleX"
    return None


def pick_lean_forward_param(available: set[str]) -> str | None:
    if "ParamBodyAngleZ" in available:
        return "ParamBodyAngleZ"
    if "ParamBodyAngleY" in available:
        return "ParamBodyAngleY"
    return None
