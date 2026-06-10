"""设置窗通用控件：表格勾选列等。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem


class TableCheckDelegate(QStyledItemDelegate):
    """表格内勾选列：圆角方框 + 对勾，避免系统默认蓝框。"""

    BOX = 18
    RADIUS = 5
    COLOR_OFF_BORDER = QColor("#C7C7CC")
    COLOR_OFF_BG = QColor("#FFFFFF")
    COLOR_ON_BG = QColor("#007AFF")
    COLOR_ON_BORDER = QColor("#007AFF")
    COLOR_MARK = QColor("#FFFFFF")

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
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor("#F0F7FF"))
        border = self.COLOR_ON_BORDER if checked else self.COLOR_OFF_BORDER
        bg = self.COLOR_ON_BG if checked else self.COLOR_OFF_BG
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(bg)
        painter.drawRoundedRect(box, self.RADIUS, self.RADIUS)
        if checked:
            painter.setPen(QPen(self.COLOR_MARK, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            x, y, w, h = box.x(), box.y(), box.width(), box.height()
            painter.drawLine(x + 4, y + h // 2, x + w // 2 - 1, y + h - 5)
            painter.drawLine(x + w // 2 - 1, y + h - 5, x + w - 4, y + 4)
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
            return QSize(self.BOX + 12, self.BOX + 8)
        return super().sizeHint(option, index)
