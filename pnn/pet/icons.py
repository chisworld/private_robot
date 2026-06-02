"""桌宠 UI 矢量图标（不依赖 emoji / 外部资源）。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


def _draw_mic(painter: QPainter, size: int, *, active: bool) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor("#dc2626") if active else QColor("#1f2937")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(c)
    s = size
    # 麦头
    cap_w = int(s * 0.36)
    cap_h = int(s * 0.48)
    cap_x = (s - cap_w) // 2
    cap_y = int(s * 0.12)
    painter.drawRoundedRect(cap_x, cap_y, cap_w, cap_h, cap_w // 2, cap_w // 2)
    # U 形支架
    painter.setPen(c)
    pen_w = max(2, s // 10)
    painter.setPen(pen_w)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    arc_x = cap_x - pen_w
    arc_y = cap_y + cap_h // 3
    arc_w = cap_w + pen_w * 2
    arc_h = int(s * 0.34)
    painter.drawArc(arc_x, arc_y, arc_w, arc_h, 0 * 16, 180 * 16)
    # 杆 + 底座
    stem_x = s // 2
    stem_y1 = arc_y + arc_h - pen_w
    stem_y2 = int(s * 0.78)
    painter.drawLine(stem_x, stem_y1, stem_x, stem_y2)
    base_w = int(s * 0.42)
    base_x = (s - base_w) // 2
    base_y = stem_y2
    painter.drawLine(base_x, base_y, base_x + base_w, base_y)


def mic_icon(*, active: bool = False, size: int = 20) -> QIcon:
    px = max(16, size + 8)
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    _draw_mic(painter, px - 4, active=active)
    painter.end()
    icon = QIcon(pixmap)
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    return icon


def mic_icon_size() -> QSize:
    return QSize(20, 20)
