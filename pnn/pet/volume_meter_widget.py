"""ASR 音量条（与 Web VolumeMeter 一致）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

_DISPLAY_MAX = 0.45


def _to_percent(value: float) -> float:
    return min(100.0, max(0.0, (value / _DISPLAY_MAX) * 100.0))


class VolumeMeterWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level = 0.0
        self._threshold = 0.03
        self._is_speech = False
        self.setMinimumHeight(48)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._bar = _MeterBar()
        lay.addWidget(self._bar)
        self._label = QLabel("音量 0.000 · 阈值 0.030")
        self._label.setStyleSheet("color: #64748b; font-size: 11px;")
        lay.addWidget(self._label)

    def set_level(self, energy: float, threshold: float, *, is_speech: bool = False) -> None:
        self._level = max(0.0, float(energy))
        self._threshold = max(0.001, float(threshold))
        self._is_speech = is_speech
        self._bar.set_values(self._level, self._threshold)
        speech_hint = " · 已触发" if is_speech else ""
        color = "#6366f1" if is_speech else "#64748b"
        self._label.setText(
            f"音量 {self._level:.3f} · 阈值 {self._threshold:.3f}{speech_hint}"
        )
        self._label.setStyleSheet(f"color: {color}; font-size: 11px;")


class _MeterBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level = 0.0
        self._threshold = 0.03
        self.setFixedHeight(14)

    def set_values(self, level: float, threshold: float) -> None:
        self._level = level
        self._threshold = threshold
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor("#e2e8f0")))
        painter.setBrush(QColor("#f1f5f9"))
        painter.drawRoundedRect(r, 7, 7)

        fill_w = int(r.width() * _to_percent(self._level) / 100.0)
        if fill_w > 0:
            grad = QLinearGradient(r.left(), 0, r.left() + fill_w, 0)
            grad.setColorAt(0, QColor("#34d399"))
            grad.setColorAt(0.5, QColor("#fbbf24"))
            grad.setColorAt(1, QColor("#ef4444"))
            fill_rect = r.adjusted(0, 0, -(r.width() - fill_w), 0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawRoundedRect(fill_rect, 6, 6)

        tx = r.left() + int(r.width() * _to_percent(self._threshold) / 100.0)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(tx, r.top() + 1, tx, r.bottom() - 1)
        painter.end()
