"""桌宠 Live2D 模型路径（live2d/14酱）。"""

from __future__ import annotations

from pathlib import Path

from pnn.core.paths import live2d_model_dir

MODEL_DIR = live2d_model_dir()
MODEL_JSON = MODEL_DIR / "我也要死吗.model3.json"
DEFAULT_EXPRESSION = "我也要死吗"
MODEL_NEUTRAL_EXPRESSION = DEFAULT_EXPRESSION
# 模型水印开关（关闭水印.exp3.json → CheekPuff2 = 1）
WATERMARK_PARAM_ID = "CheekPuff2"
WATERMARK_HIDE_VALUE = 1.0
HIDE_WATERMARK_EXPRESSION = "关闭水印"
# 模型内置对话框（默认表情「我也要死吗」会打开 Param37）
MODEL_DIALOG_PARAM_ID = "Param37"
MODEL_DIALOG_HIDE_VALUE = 0.0

# 全身可见范围（决定窗口宽高比）
MODEL_CONTENT_CROP = (0.18, 0.10, 0.82, 0.98)

# 缩放用更紧范围（用户可在设置里用 crop_shrink / fill_percent 继续收紧）
MODEL_TIGHT_CROP = (0.32, 0.20, 0.68, 0.97)

INITIAL_CHARACTER_SCALE = 1.5
DEFAULT_CHARACTER_WIDTH = 200

MODEL_FILL_FACTOR = 1.65
