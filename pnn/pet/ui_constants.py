"""桌宠界面固定样式（不在设置中暴露）。"""

CHAT_FONT_SIZE = 20
CHAT_FONT_FAMILY = "Microsoft YaHei UI"
CHAT_TEXT_COLOR = "#111827"

# AI 输出气泡窗（深灰底 + 白字，参考模型原对话框样式）
OUTPUT_FONT_SIZE = 20
OUTPUT_FONT_FAMILY = "Microsoft YaHei UI"
OUTPUT_TEXT_COLOR = "#FFFFFF"
OUTPUT_BG_TRANSPARENCY_PERCENT = 0

BUBBLE_BORDER_WIDTH = 0
BUBBLE_DEFAULT_WIDTH = 220
BUBBLE_DEFAULT_HEIGHT = 88

# ASR：识别结果显示时长（毫秒），超时后清空输入框；常开模式下随后自动发送
ASR_FINAL_HOLD_MS = 3000
ASR_INPUT_IDLE_CLEAR_MS = 3000

# 人物大小（设置页与滚轮缩放共用；下限尽量低以便滚轮缩小）
CHARACTER_SCALE_MIN = 0.01
CHARACTER_SCALE_MAX = 10.0
CHARACTER_SCALE_SPIN_STEP_PERCENT = 10

# 人物窗外框（内区 live2d）可缩到的最小宽高；滚轮与拖边共用
CHARACTER_BODY_MIN_WIDTH = 32
CHARACTER_BODY_MIN_HEIGHT = 32
# 滚轮仅改外框宽/高时的步进（像素）
CHARACTER_FRAME_WHEEL_STEP_PX = 10


def character_window_minimum_size(*, margin: int = 2) -> tuple[int, int]:
    """含边距的窗口 minimumSize。"""
    return (
        CHARACTER_BODY_MIN_WIDTH + margin * 2,
        CHARACTER_BODY_MIN_HEIGHT + margin * 2,
    )


def clamp_character_body_size(width: int, height: int) -> tuple[int, int]:
    return (
        max(CHARACTER_BODY_MIN_WIDTH, int(width)),
        max(CHARACTER_BODY_MIN_HEIGHT, int(height)),
    )


def clamp_character_scale(scale: float) -> float:
    return max(CHARACTER_SCALE_MIN, min(CHARACTER_SCALE_MAX, float(scale)))
