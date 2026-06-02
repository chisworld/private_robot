"""无边框窗口：描边 + 八向拖拽缩放（类似浏览器拖边改大小）。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QWidget

BORDER_COLOR = QColor(0, 0, 0, 255)
BORDER_WIDTH = 1
RESIZE_MARGIN = 8


class FrameBorderMixin:
    """在 paintEvent 中绘制圆角描边；配合 EdgeResizeMixin 使用。"""

    _draw_frame_border = True

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not getattr(self, "_draw_frame_border", True):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(BORDER_COLOR)
        pen.setWidth(BORDER_WIDTH)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        r = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRect(r)
        painter.end()


class EdgeResizeMixin:
    """鼠标靠近边缘/四角时拖拽缩放窗口。"""

    _resize_margin = RESIZE_MARGIN
    _resize_active = False
    _resize_edges: tuple[bool, bool, bool, bool] = (False, False, False, False)
    _resize_origin: QPoint | None = None
    _resize_geom: QRect | None = None

    def _edge_at(self, pos: QPoint) -> tuple[bool, bool, bool, bool]:
        m = self._resize_margin
        w, h = self.width(), self.height()
        left = pos.x() < m
        right = pos.x() > w - m
        top = pos.y() < m
        bottom = pos.y() > h - m
        return left, right, top, bottom

    def _cursor_for_edges(self, edges: tuple[bool, bool, bool, bool]) -> Qt.CursorShape:
        left, right, top, bottom = edges
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def _on_resize_hover(self, pos: QPoint) -> None:
        if getattr(self, "_drag_active", False) or getattr(self, "_resize_active", False):
            return
        edges = self._edge_at(pos)
        if any(edges):
            self.setCursor(QCursor(self._cursor_for_edges(edges)))
        else:
            self.unsetCursor()

    def _try_begin_resize(self, global_pos: QPoint, local_pos: QPoint) -> bool:
        edges = self._edge_at(local_pos)
        if not any(edges):
            return False
        self._resize_active = True
        self._resize_edges = edges
        self._resize_origin = global_pos
        self._resize_geom = self.geometry()
        self.setCursor(QCursor(self._cursor_for_edges(edges)))
        return True

    def _apply_resize(self, global_pos: QPoint) -> None:
        if not self._resize_active or self._resize_origin is None or self._resize_geom is None:
            return
        delta = global_pos - self._resize_origin
        g = QRect(self._resize_geom)
        left, right, top, bottom = self._resize_edges
        min_w = max(self.minimumWidth(), 120)
        min_h = max(self.minimumHeight(), 80)
        max_w = getattr(self, "_resize_max_width", 16777215)
        max_h = getattr(self, "_resize_max_height", 16777215)

        if left:
            new_left = g.left() + delta.x()
            max_left = g.right() - min_w
            g.setLeft(min(new_left, max_left))
        if right:
            g.setRight(max(g.left() + min_w, g.right() + delta.x()))
        if top:
            new_top = g.top() + delta.y()
            max_top = g.bottom() - min_h
            g.setTop(min(new_top, max_top))
        if bottom:
            g.setBottom(max(g.top() + min_h, g.bottom() + delta.y()))

        g.setWidth(min(max(g.width(), min_w), max_w))
        g.setHeight(min(max(g.height(), min_h), max_h))
        self.setGeometry(g)

    def _end_resize(self) -> None:
        self._resize_active = False
        self._resize_edges = (False, False, False, False)
        self._resize_origin = None
        self._resize_geom = None
        self.unsetCursor()


class DragMoveMixin:
    """在客户区拖拽移动窗口（避开边缘缩放区与控件）。"""

    _drag_start: QPoint | None = None
    _window_start: QPoint | None = None
    _drag_active = False

    def _drag_margin_top(self) -> int:
        return 36

    def _can_drag_from(self, pos: QPoint) -> bool:
        edges = self._edge_at(pos) if hasattr(self, "_edge_at") else (False, False, False, False)
        if any(edges):
            return False
        return pos.y() < self._drag_margin_top() or not self._hit_child_at(pos)

    def _hit_child_at(self, pos: QPoint) -> bool:
        child = self.childAt(pos)
        if child is None:
            return False
        if child is self:
            return False
        return True

    def _try_begin_drag(self, global_pos: QPoint, local_pos: QPoint) -> bool:
        if not self._can_drag_from(local_pos):
            return False
        self._drag_start = global_pos
        self._window_start = self.frameGeometry().topLeft()
        self._drag_active = False
        return True

    def _apply_drag(self, global_pos: QPoint) -> None:
        if self._drag_start is None or self._window_start is None:
            return
        delta = global_pos - self._drag_start
        if not self._drag_active and (abs(delta.x()) > 4 or abs(delta.y()) > 4):
            self._drag_active = True
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        if self._drag_active:
            self.move(self._window_start + delta)

    def _end_drag(self) -> None:
        self._drag_start = None
        self._window_start = None
        self._drag_active = False
        if not getattr(self, "_resize_active", False):
            self.unsetCursor()
