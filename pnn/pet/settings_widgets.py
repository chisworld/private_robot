"""设置窗通用控件：表格勾选列等。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QRect, QSize
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem


class TableCheckDelegate(QStyledItemDelegate):
    """表格内勾选列：发光宝石风格圆角方框 + 对勾，深色主题。"""

    BOX = 20
    RADIUS = 6

    COLOR_OFF_BORDER = QColor("#334155")
    COLOR_OFF_BG_TOP = QColor(30, 41, 59)
    COLOR_OFF_BG_BOT = QColor(15, 23, 42)

    COLOR_ON_BORDER = QColor("#818cf8")
    COLOR_ON_BG_TOP = QColor("#818cf8")
    COLOR_ON_BG_MID = QColor("#6366f1")
    COLOR_ON_BG_BOT = QColor("#4f46e5")

    COLOR_HOVER_BORDER = QColor("#6366f1")
    COLOR_HOVER_BG_TOP = QColor(49, 46, 129)
    COLOR_HOVER_BG_BOT = QColor(30, 41, 59)

    COLOR_MARK = QColor("#ffffff")
    COLOR_HOVER_FILL = QColor(99, 102, 241, 20)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        if index.data(Qt.ItemDataRole.CheckStateRole) is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        rect = option.rect
        box = QRect(
            rect.x() + (rect.width() - self.BOX) // 2,
            rect.y() + (rect.height() - self.BOX) // 2,
            self.BOX,
            self.BOX,
        )

        # ── 行悬停背景 ──
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if hovered:
            painter.fillRect(rect, self.COLOR_HOVER_FILL)

        if checked:
            # ── 选中态：垂直渐变宝石方块 ──
            border_color = self.COLOR_ON_BORDER
            grad = QLinearGradient(box.topLeft(), box.bottomLeft())
            grad.setColorAt(0.0, self.COLOR_ON_BG_TOP)
            grad.setColorAt(0.45, self.COLOR_ON_BG_MID)
            grad.setColorAt(1.0, self.COLOR_ON_BG_BOT)
            painter.setPen(QPen(border_color, 1.5))
            painter.setBrush(grad)
            painter.drawRoundedRect(box, self.RADIUS, self.RADIUS)

            # ── 对勾（发光白） ──
            painter.setPen(QPen(self.COLOR_MARK, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            x, y, w, h = box.x(), box.y(), box.width(), box.height()
            painter.drawLine(x + 4, y + h // 2, x + w // 2 - 1, y + h - 5)
            painter.drawLine(x + w // 2 - 1, y + h - 5, x + w - 4, y + 5)
        else:
            # ── 非选中态：深色玻璃方块 ──
            border = self.COLOR_HOVER_BORDER if hovered else self.COLOR_OFF_BORDER
            grad = QLinearGradient(box.topLeft(), box.bottomLeft())
            if hovered:
                grad.setColorAt(0.0, self.COLOR_HOVER_BG_TOP)
                grad.setColorAt(1.0, self.COLOR_HOVER_BG_BOT)
            else:
                grad.setColorAt(0.0, self.COLOR_OFF_BG_TOP)
                grad.setColorAt(1.0, self.COLOR_OFF_BG_BOT)
            painter.setPen(QPen(border, 1.5))
            painter.setBrush(grad)
            painter.drawRoundedRect(box, self.RADIUS, self.RADIUS)

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if index.data(Qt.ItemDataRole.CheckStateRole) is None:
            return super().editorEvent(event, model, option, index)
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
            model.setData(
                index,
                Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,
                Qt.ItemDataRole.CheckStateRole,
            )
            return True
        return False

    def sizeHint(self, option, index) -> QSize:
        if index.data(Qt.ItemDataRole.CheckStateRole) is not None:
            return QSize(self.BOX + 14, self.BOX + 10)
        return super().sizeHint(option, index)
