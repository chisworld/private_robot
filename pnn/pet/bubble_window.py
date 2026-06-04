"""独立 AI 输出框：单个 SpeechBubble，无叠加命中层（避免叠成两个气泡）。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget

from pnn.pet.frame_mixin import EdgeResizeMixin
from pnn.pet.preferences import PetUiPreferences
from pnn.pet.speech_bubble import SpeechBubble
from pnn.pet.ui_constants import (
    BUBBLE_DEFAULT_HEIGHT,
    BUBBLE_DEFAULT_WIDTH,
    OUTPUT_BG_TRANSPARENCY_PERCENT,
    OUTPUT_FONT_FAMILY,
    OUTPUT_FONT_SIZE,
    OUTPUT_TEXT_COLOR,
)

_BUBBLE_RESIZE_MARGIN = 12


class BubbleWindow(QWidget, EdgeResizeMixin):
    closed = Signal()
    minimized = Signal()
    geometry_changed = Signal()

    _resize_margin = _BUBBLE_RESIZE_MARGIN

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("14酱 · 输出")
        self.resize(BUBBLE_DEFAULT_WIDTH, BUBBLE_DEFAULT_HEIGHT)
        self.setMinimumSize(1, 1)
        self._geom_save_timer = QTimer(self)
        self._geom_save_timer.setSingleShot(True)
        self._geom_save_timer.setInterval(350)
        self._geom_save_timer.timeout.connect(self.geometry_changed.emit)
        self._resize_max_width = 16777215
        self._resize_max_height = 16777215
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        self._drag_start: QPoint | None = None
        self._window_start: QPoint | None = None
        self._drag_active = False

        self._speech = SpeechBubble(
            self,
            flexible=True,
            font_size=OUTPUT_FONT_SIZE,
            text_color=OUTPUT_TEXT_COLOR,
            bg_transparency_percent=OUTPUT_BG_TRANSPARENCY_PERCENT,
            font_family=OUTPUT_FONT_FAMILY,
        )

    def restore_geometry(self, prefs: PetUiPreferences) -> None:
        w = prefs.bubble_window_w if prefs.bubble_window_w > 0 else BUBBLE_DEFAULT_WIDTH
        h = prefs.bubble_window_h if prefs.bubble_window_h > 0 else BUBBLE_DEFAULT_HEIGHT
        if prefs.bubble_window_x >= 0 and prefs.bubble_window_y >= 0:
            self.setGeometry(prefs.bubble_window_x, prefs.bubble_window_y, w, h)
        else:
            self.resize(w, h)

    def capture_geometry(self) -> tuple[int, int, int, int]:
        g = self.geometry()
        return g.x(), g.y(), g.width(), g.height()

    def _schedule_geometry_save(self) -> None:
        self._geom_save_timer.start()

    def apply_preferences(self, prefs: PetUiPreferences) -> None:
        self._speech.apply_prefs(
            font_size=prefs.bubble_font_size,
            width_px=prefs.bubble_width_px,
            height_px=prefs.bubble_height_px,
            text_color=prefs.bubble_text_color,
            bg_color=prefs.bubble_bg_color,
            bg_transparency_percent=prefs.bubble_bg_transparency_percent,
            page_interval_ms=prefs.page_interval_ms,
            font_family=prefs.bubble_font_family,
            use_imported_font=prefs.use_imported_font,
        )
        if self.has_content():
            self._speech.set_text(self._speech.body_text())

    def _client_rect(self) -> QRect:
        return self.rect()

    _THINKING_TEXT = ("…", "...")

    def has_content(self) -> bool:
        return bool(self._speech.body_text())

    def suggested_read_ms(self) -> int:
        return self._speech.suggested_read_ms()

    def is_thinking(self) -> bool:
        return self._speech.body_text() in self._THINKING_TEXT

    def set_text(self, text: str, *, stream: bool = False) -> None:
        body = (text or "").strip()
        if not body:
            self.clear()
            return
        self._speech.set_text(body, stream=stream)
        if not self.isVisible() or self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()

    def clear(self) -> None:
        self._speech.clear()
        self.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._speech.setGeometry(self._client_rect())
        self._speech.on_viewport_resized()

    def _on_resize_edges(self, pos: QPoint) -> tuple[bool, bool, bool, bool]:
        return self._edge_at(pos)

    def _can_drag_at(self, pos: QPoint) -> bool:
        return self._client_rect().contains(pos) and not any(self._on_resize_edges(pos))

    def _try_begin_drag(self, global_pos: QPoint, local_pos: QPoint) -> bool:
        if not self._can_drag_at(local_pos):
            return False
        self._drag_start = global_pos
        self._window_start = self.frameGeometry().topLeft()
        self._drag_active = True
        self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        self.grabMouse()
        return True

    def _apply_drag(self, global_pos: QPoint) -> None:
        if self._drag_start is None or self._window_start is None:
            return
        self.move(self._window_start + global_pos - self._drag_start)

    def _end_drag(self) -> None:
        if self._drag_start is not None:
            self.releaseMouse()
        self._drag_start = None
        self._window_start = None
        self._drag_active = False
        if not self._resize_active:
            self.unsetCursor()
        self._schedule_geometry_save()

    def _try_begin_resize(self, global_pos: QPoint, local_pos: QPoint) -> bool:
        edges = self._on_resize_edges(local_pos)
        if not any(edges):
            return False
        self._resize_active = True
        self._resize_edges = edges
        self._resize_origin = global_pos
        self._resize_geom = QRect(self.geometry())
        self.setCursor(QCursor(self._cursor_for_edges(edges)))
        self.grabMouse()
        return True

    def _apply_resize(self, global_pos: QPoint) -> None:
        if not self._resize_active or self._resize_origin is None or self._resize_geom is None:
            return
        delta = global_pos - self._resize_origin
        g = QRect(self._resize_geom)
        left, right, top, bottom = self._resize_edges
        min_w = max(1, self.minimumWidth())
        min_h = max(1, self.minimumHeight())
        max_w = self._resize_max_width
        max_h = self._resize_max_height

        if left:
            new_left = g.left() + delta.x()
            g.setLeft(min(new_left, g.right() - min_w))
        if right:
            g.setRight(max(g.left() + min_w, g.right() + delta.x()))
        if top:
            new_top = g.top() + delta.y()
            g.setTop(min(new_top, g.bottom() - min_h))
        if bottom:
            g.setBottom(max(g.top() + min_h, g.bottom() + delta.y()))

        g.setWidth(min(max(g.width(), min_w), max_w))
        g.setHeight(min(max(g.height(), min_h), max_h))
        self.setGeometry(g)

    def _end_resize(self) -> None:
        if self._resize_active:
            self.releaseMouse()
        self._resize_active = False
        self._resize_edges = (False, False, False, False)
        self._resize_origin = None
        self._resize_geom = None
        self.unsetCursor()
        self._schedule_geometry_save()


    def _minimize_from_menu(self) -> None:
        self.showMinimized()
        self.minimized.emit()

    def contextMenuEvent(self, event) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self._can_drag_at(pos):
            self._minimize_from_menu()
            event.accept()

    def mousePressEvent(self, event) -> None:
        pos = self._client_pos(event)
        gpos = self._global_pos(event)
        if event.button() == Qt.MouseButton.RightButton:
            if self._can_drag_at(pos):
                self._minimize_from_menu()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self._try_begin_resize(gpos, pos):
                event.accept()
                return
            if self._try_begin_drag(gpos, pos):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = self._client_pos(event)
        gpos = self._global_pos(event)
        if self._resize_active:
            self._apply_resize(gpos)
            event.accept()
            return
        if self._drag_active and event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_drag(gpos)
            event.accept()
            return
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_drag(gpos)
            event.accept()
            return
        edges = self._on_resize_edges(pos)
        if any(edges):
            self._on_resize_hover(pos)
        elif self._can_drag_at(pos):
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        else:
            self.unsetCursor()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._end_resize()
        self._end_drag()
        event.accept()

    def _client_pos(self, event) -> QPoint:
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _global_pos(self, event) -> QPoint:
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        return event.globalPos()
