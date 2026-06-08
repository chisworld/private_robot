"""GIF → Live2D 表情/动作映射：从模型目录读取 GIF，匹配对应表情并触发。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# GIF 中文名 → 表情/动作映射（血裔少女模型）
_GIF_EXPRESSION_MAP: dict[str, str] = {
    "变小": "shrink",
    "抱玩偶": "little bear",
    "害羞抱熊": "shy bear",
    "变身变小": "transform shrink",
    "镰刀": "jump",           # 挥舞镰刀 → 跳起来
    "黑脸": "Black",
    "红色": "blush",
    "白色": "Veil",
    "低头": "deep_bow",       # 低头 → 深鞠躬
}

# 表情名 → motion3 文件 stem（模型内无同名 .motion3.json 时的显式绑定）
_EXPRESSION_MOTION_STEMS: dict[str, str] = {
    "shrink": "Scene1",  # 里想奈：Scene1 为变小过渡动画，shrink.exp3 为终态
    "transform shrink": "Scene1",  # 变身+变小：同一过渡动画，终态为骷髅+缩小
}

# 尺寸+帧数 → 动作（hash 命名的 GIF）
_FINGERPRINT_MAP: dict[str, str] = {
    "611_601_47": "deep_bow",
    "739_786_57": "jump",
    "648_693_42": "idle",
    "648_693_57": "little bear",
    "739_786_52": "shrink",
    "739_786_54": "Veil",
    "739_786_49": "blush",
    "648_693_41": "Black",
}

# 自定义动作的关键帧（参数名 → [(时间ms, 值), ...]）
_CUSTOM_MOTIONS: dict[str, list[tuple[str, list[tuple[int, float]]]]] = {
    "__bow": [
        ("ParamAngleX", [
            (0, 0.0),
            (300, 14.0),
            (800, 14.0),
            (1300, 0.0),
        ]),
    ],
}


def _motion_duration_sec(path: Path) -> float:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return max(0.1, float(data.get("Meta", {}).get("Duration", 3.0)))
    except Exception:
        return 3.0


def discover_expression_motions(model_dir: Path) -> dict[str, tuple[str, float]]:
    """扫描模型目录：表情名 → (motion stem, 时长秒)。用于播放完整 motion3 并保持终态。"""
    model_dir = Path(model_dir)
    out: dict[str, tuple[str, float]] = {}
    if not model_dir.is_dir():
        return out

    for expr, stem in _EXPRESSION_MOTION_STEMS.items():
        exp_path = model_dir / f"{expr}.exp3.json"
        motion_path = model_dir / f"{stem}.motion3.json"
        if exp_path.is_file() and motion_path.is_file():
            out[expr] = (stem, _motion_duration_sec(motion_path))

    for exp_path in sorted(model_dir.glob("*.exp3.json")):
        name = exp_path.name
        if name.endswith(".exp3.json"):
            name = name[: -len(".exp3.json")]
        if name in out:
            continue
        motion_path = model_dir / f"{name}.motion3.json"
        if motion_path.is_file():
            out[name] = (name, _motion_duration_sec(motion_path))

    return out


def _extract_chinese(name: str) -> str:
    """从文件名提取中文部分。"""
    chinese = re.findall(r"[一-鿿]+", name)
    return "".join(chinese) if chinese else ""


def _gif_fingerprint(gif_path: Path) -> str:
    """返回 GIF 的特征指纹 'width_height_frames'。"""
    try:
        from PIL import Image
        img = Image.open(gif_path)
        w, h = img.size
        n = 0
        try:
            while True:
                n += 1
                img.seek(n)
        except EOFError:
            pass
        return f"{w}_{h}_{n}"
    except Exception:
        return ""


def _build_map_from_dir(model_dir: Path) -> dict[str, str]:
    """扫描模型目录下的 GIF 和表达式，自动建立映射。"""
    gif_to_expr: dict[str, str] = {}
    expressions: set[str] = set()

    for exp_path in sorted(model_dir.glob("*.exp3.json")):
        name = exp_path.stem
        if name.endswith(".exp3"):
            name = name[:-5]
        expressions.add(name)

    for gif_path in sorted(model_dir.glob("*.gif")):
        gif_name = gif_path.stem
        matched: str | None = None

        # 1. 中文关键词匹配（包括自定义动作如 __bow）
        chinese = _extract_chinese(gif_name)
        for keyword, expr_name in _GIF_EXPRESSION_MAP.items():
            if keyword in chinese:
                if expr_name.startswith("__") or expr_name in expressions:
                    matched = expr_name
                    break

        # 2. 英文表情名匹配
        if not matched:
            gif_lower = gif_name.lower()
            for expr in sorted(expressions, key=len, reverse=True):
                if len(expr) >= 3 and expr.lower() in gif_lower:
                    matched = expr
                    break

        # 3. 指纹匹配（hash 命名的 GIF）
        if not matched:
            fp = _gif_fingerprint(gif_path)
            matched = _FINGERPRINT_MAP.get(fp)

        if matched:
            gif_to_expr[gif_name] = matched

    return gif_to_expr


def discover_gif_motions(model_dir: Path) -> list[dict[str, Any]]:
    """扫描模型目录，返回 GIF 动作列表。"""
    model_dir = Path(model_dir)
    expr_map = _build_map_from_dir(model_dir)
    motions: list[dict[str, Any]] = []

    for gif_path in sorted(model_dir.glob("*.gif")):
        name = gif_path.stem
        expr_name = expr_map.get(name, "")
        is_custom = expr_name.startswith("__")
        frames = _count_gif_frames(gif_path)

        motions.append({
            "name": name,
            "expression": expr_name[2:] if is_custom else expr_name,
            "is_custom": is_custom,
            "path": str(gif_path.resolve()),
            "display": _display_label(name),
            "frames": frames,
        })

    return motions


def _count_gif_frames(gif_path: Path) -> int:
    try:
        from PIL import Image
        img = Image.open(gif_path)
        n = 0
        try:
            while True:
                n += 1
                img.seek(n)
        except EOFError:
            pass
        return n
    except Exception:
        return 0


def _display_label(name: str) -> str:
    chinese = _extract_chinese(name)
    if chinese:
        return chinese
    return name[:12] if len(name) > 12 else name


def get_custom_motion_frames(name: str) -> list[tuple[str, list[tuple[int, float]]]]:
    """获取自定义动作的关键帧列表。"""
    key = f"__{name}"
    return _CUSTOM_MOTIONS.get(key, [])


def build_gif_motion_json(gif_name: str, model_dir: Path) -> Path | None:
    """为自定义 GIF 动作生成 .motion3.json 文件。"""
    custom_frames = get_custom_motion_frames(gif_name)
    if not custom_frames:
        return None

    duration_ms = max(
        (max(t for t, _ in frames) for _, frames in custom_frames), default=1000
    )

    motion = {
        "Version": 3,
        "Meta": {
            "Name": gif_name,
            "Duration": duration_ms / 1000.0,
            "Fps": 30.0,
            "Loop": True,
            "AreBeziersRestricted": True,
            "CurveCount": len(custom_frames),
            "TotalSegmentCount": sum(len(frames) for _, frames in custom_frames),
            "TotalPointCount": sum(len(frames) for _, frames in custom_frames),
        },
        "Curves": [
            {
                "Target": "Parameter",
                "Id": param_id,
                "Segments": [
                    {
                        "Keys": [
                            {"Time": t / 1000.0, "Value": v}
                            for t, v in sorted(keyframes, key=lambda x: x[0])
                        ]
                    }
                ],
            }
            for param_id, keyframes in custom_frames
        ],
    }

    out_path = model_dir / f"{gif_name}.motion3.json"
    out_path.write_text(
        json.dumps(motion, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_path
