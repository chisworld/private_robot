"""桌宠 Live2D 模型路径（首次使用时再解析，避免拖慢进程启动）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 全身可见范围（决定窗口宽高比）
MODEL_CONTENT_CROP = (0.18, 0.10, 0.82, 0.98)

# 缩放用更紧范围（用户可在设置里用 crop_shrink / fill_percent 继续收紧）
MODEL_TIGHT_CROP = (0.32, 0.20, 0.68, 0.97)

INITIAL_CHARACTER_SCALE = 1.5
DEFAULT_CHARACTER_WIDTH = 200

MODEL_FILL_FACTOR = 1.65

# 模型内置对话框（默认表情会打开 Param37）
MODEL_DIALOG_PARAM_ID = "Param37"
MODEL_DIALOG_HIDE_VALUE = 0.0

_LAZY_ATTRS = frozenset(
    {
        "MODEL_DIR",
        "MODEL_JSON",
        "MODEL_NAME",
        "DEFAULT_EXPRESSION",
        "MODEL_NEUTRAL_EXPRESSION",
        "WATERMARK_PARAM_ID",
        "HIDE_WATERMARK_EXPRESSION",
        "WATERMARK_HIDE_VALUE",
    }
)

_model_cache: dict[str, Any] = {}


def _model_name_from_json(json_path: Path) -> str:
    name = json_path.name
    if name.endswith(".model3.json"):
        return name[: -len(".model3.json")]
    return json_path.stem


def _discover_watermark_settings(model_dir: Path) -> tuple[str, str, float]:
    patterns = ("*水印*.exp3.json", "关闭水印.exp3.json", "*watermark*.exp3.json")
    for pattern in patterns:
        for path in sorted(model_dir.glob(pattern)):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                params = data.get("Parameters") or []
                if params:
                    param_id = str(params[0].get("Id", "CheekPuff2"))
                    value = float(params[0].get("Value", 1.0))
                    name = path.name
                    if name.endswith(".exp3.json"):
                        name = name[: -len(".exp3.json")]
                    return param_id, name, value
            except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
                continue
    return "CheekPuff2", "关闭水印", 1.0


def _bootstrap_model_paths() -> None:
    if _model_cache:
        return
    from pnn.core.paths import live2d_model_dir, live2d_model_json

    model_dir = live2d_model_dir()
    model_json = live2d_model_json()
    model_name = _model_name_from_json(model_json)
    wm_param, wm_expr, wm_val = _discover_watermark_settings(model_dir)
    _model_cache.update(
        {
            "MODEL_DIR": model_dir,
            "MODEL_JSON": model_json,
            "MODEL_NAME": model_name,
            "DEFAULT_EXPRESSION": model_name,
            "MODEL_NEUTRAL_EXPRESSION": model_name,
            "WATERMARK_PARAM_ID": wm_param,
            "HIDE_WATERMARK_EXPRESSION": wm_expr,
            "WATERMARK_HIDE_VALUE": wm_val,
        }
    )


def invalidate_model_paths() -> None:
    _model_cache.clear()


def __getattr__(name: str) -> Any:
    if name in _LAZY_ATTRS:
        _bootstrap_model_paths()
        return _model_cache[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
