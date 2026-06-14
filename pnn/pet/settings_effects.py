"""设置窗视觉特效 — 光晕、渐变边框、脉冲动画。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSequentialAnimationGroup,
    Qt,
    QTimer,
    Property,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget


# ── 标准阴影预制 ──────────────────────────────────────────────────────────

def apply_soft_shadow(
    widget: QWidget,
    *,
    blur: float = 38,
    offset_y: float = 10,
    alpha: int = 35,
    color: QColor | None = None,
) -> QGraphicsDropShadowEffect:
    """深色玻璃拟态阴影 — 柔和的紫蓝色光晕。"""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, offset_y)
    if color is not None:
        effect.setColor(color)
    else:
        effect.setColor(QColor(99, 102, 241, alpha))
    widget.setGraphicsEffect(effect)
    return effect


def apply_glow_shadow(
    widget: QWidget,
    *,
    blur: float = 45,
    offset_y: float = 6,
    alpha: int = 50,
) -> QGraphicsDropShadowEffect:
    """强化光晕阴影 — 用于主卡片，更强的紫蓝辉光。"""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, offset_y)
    effect.setColor(QColor(99, 102, 241, alpha))
    widget.setGraphicsEffect(effect)
    return effect


def apply_cyan_accent_shadow(
    widget: QWidget,
    *,
    blur: float = 32,
    offset_y: float = 4,
    alpha: int = 40,
) -> QGraphicsDropShadowEffect:
    """青色点缀阴影 — 用于次要面板或信息栏。"""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, offset_y)
    effect.setColor(QColor(6, 182, 212, alpha))
    widget.setGraphicsEffect(effect)
    return effect


# ── 脉冲光晕动画 ──────────────────────────────────────────────────────────

class PulseAnimation:
    """在控件上循环脉冲光晕（alpha 在 min/max 之间缓动）。"""

    def __init__(
        self,
        widget: QWidget,
        *,
        min_alpha: int = 15,
        max_alpha: int = 55,
        duration_ms: int = 2200,
        blur: float = 40,
        offset_y: float = 8,
    ) -> None:
        self._widget = widget
        self._effect = QGraphicsDropShadowEffect(widget)
        self._effect.setBlurRadius(blur)
        self._effect.setOffset(0, offset_y)
        self._min = min_alpha
        self._max = max_alpha
        widget.setGraphicsEffect(self._effect)

        self._anim = QPropertyAnimation(self._effect, b"alpha")
        self._anim.setDuration(duration_ms)
        self._anim.setStartValue(min_alpha)
        self._anim.setEndValue(max_alpha)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)

        self._reverse = QPropertyAnimation(self._effect, b"alpha")
        self._reverse.setDuration(duration_ms)
        self._reverse.setStartValue(max_alpha)
        self._reverse.setEndValue(min_alpha)
        self._reverse.setEasingCurve(QEasingCurve.Type.InOutSine)

        self._group = QSequentialAnimationGroup()
        self._group.addAnimation(self._anim)
        self._group.addAnimation(self._reverse)
        self._group.setLoopCount(-1)
        # Don't auto-start; caller controls lifecycle

    def start(self) -> None:
        self._group.start()

    def stop(self) -> None:
        self._group.stop()


# ── 动态 Alpha 属性（供 QPropertyAnimation 驱动） ─────────────────────────

class _AlphaEffect(QGraphicsDropShadowEffect):
    """带可动画 alpha 通道的阴影效果。"""

    def __init__(self, parent: QWidget | None = None, alpha: int = 35) -> None:
        super().__init__(parent)
        self._alpha = alpha
        self._base_color = QColor(99, 102, 241, alpha)
        self.setColor(self._base_color)

    @Property(int)
    def alpha(self) -> int:  # type: ignore[override]
        return self._alpha

    @alpha.setter
    def alpha(self, value: int) -> None:
        self._alpha = value
        self._base_color.setAlpha(value)
        self.setColor(self._base_color)


# ── 渐变背景刷子工具 ──────────────────────────────────────────────────────

def indigo_cyan_gradient(rect: QRectF) -> QLinearGradient:
    """靛蓝→紫色→青色的水平渐变。"""
    grad = QLinearGradient(rect.topLeft(), rect.topRight())
    grad.setColorAt(0.0, QColor(99, 102, 241, 40))
    grad.setColorAt(0.35, QColor(139, 92, 246, 35))
    grad.setColorAt(0.7, QColor(167, 139, 250, 25))
    grad.setColorAt(1.0, QColor(6, 182, 212, 20))
    return grad


def accent_gradient_vertical(rect: QRectF) -> QLinearGradient:
    """紫蓝垂直渐变（卡片顶部光晕）。"""
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, QColor(99, 102, 241, 45))
    grad.setColorAt(0.5, QColor(139, 92, 246, 20))
    grad.setColorAt(1.0, QColor(15, 23, 42, 0))
    return grad


def radial_glow(center: QPointF, radius: float) -> QRadialGradient:
    """中心发光渐变 — 用于悬浮高亮。"""
    grad = QRadialGradient(center, radius)
    grad.setColorAt(0.0, QColor(99, 102, 241, 60))
    grad.setColorAt(0.4, QColor(139, 92, 246, 25))
    grad.setColorAt(0.8, QColor(6, 182, 212, 5))
    grad.setColorAt(1.0, QColor(0, 0, 0, 0))
    return grad


# ── 渐变边框绘制器 ────────────────────────────────────────────────────────

def draw_gradient_border(
    painter: QPainter,
    rect: QRectF,
    radius: float = 18.0,
    width: float = 1.5,
) -> None:
    """在指定区域绘制靛蓝→青色渐变圆角边框。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor(99, 102, 241, 80))
    grad.setColorAt(0.3, QColor(139, 92, 246, 70))
    grad.setColorAt(0.6, QColor(167, 139, 250, 50))
    grad.setColorAt(1.0, QColor(6, 182, 212, 60))

    pen = QPen(QBrush(grad), width)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


def draw_glow_underline(
    painter: QPainter,
    rect: QRectF,
    height: float = 3.0,
    radius: float = 2.0,
) -> None:
    """在标题/分隔线下绘制发光渐变下划线。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    line_rect = QRectF(rect.x(), rect.y(), rect.width(), height)
    grad = QLinearGradient(line_rect.topLeft(), line_rect.topRight())
    grad.setColorAt(0.0, QColor(99, 102, 241, 180))
    grad.setColorAt(0.5, QColor(139, 92, 246, 160))
    grad.setColorAt(1.0, QColor(6, 182, 212, 120))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(grad))
    painter.drawRoundedRect(line_rect, radius, radius)
    painter.restore()
