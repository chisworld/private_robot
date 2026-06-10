"""设置窗视觉特效（卡片阴影等）。"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget


def apply_soft_shadow(
    widget: QWidget,
    *,
    blur: float = 32,
    offset_y: float = 8,
    alpha: int = 28,
) -> None:
    """iOS 风格轻阴影，模拟卡片浮起。"""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, offset_y)
    effect.setColor(QColor(0, 90, 180, alpha))
    widget.setGraphicsEffect(effect)
