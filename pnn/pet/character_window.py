"""人物窗：可缩放、悬停人物时显示黑边，透明区鼠标穿透。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from pnn.pet.frame_mixin import DragMoveMixin, EdgeResizeMixin
from pnn.pet.image_payload import image_from_clipboard, image_from_mime, mime_has_image, qimage_to_payload
from pnn.pet.live2d_widget import Live2DWidget
from pnn.pet.paths import DEFAULT_CHARACTER_WIDTH, INITIAL_CHARACTER_SCALE
from pnn.pet.preferences import PetUiPreferences
from pnn.pet.ui_constants import (
    BUBBLE_BORDER_WIDTH,
    CHARACTER_SCALE_MAX,
    CHARACTER_SCALE_MIN,
    CHARACTER_SCALE_SPIN_STEP_PERCENT,
    clamp_character_scale,
)
from pnn.pet.win_mouse import set_click_through

_BTN_STYLE = (
    "QPushButton { background: transparent; border: none; color: #000000; font-size: 13px; }"
    "QPushButton:hover { color: #374151; }"
)


class CharacterWindow(QWidget, EdgeResizeMixin, DragMoveMixin):
    closed = Signal()
    settings_requested = Signal()
    chat_restore_requested = Signal()
    screenshot_attached = Signal(str, str)  # image_base64, image_mime
    scale_changed = Signal(float)
    size_changed_by_user = Signal(int, int)

    def __init__(self, *, character_scale: float = INITIAL_CHARACTER_SCALE, parent=None) -> None:
        super().__init__(parent)
        self._character_scale = clamp_character_scale(character_scale)
        self._custom_width = 0
        self._custom_height = 0
        self._border_visible = False
        self._hover_on_model = False
        self._click_through: bool | None = None
        self.setWindowTitle("14酱")
        self.setMinimumSize(80, 100)
        self.setMaximumSize(16777215, 16777215)
        self._resize_max_width = 16777215
        self._resize_max_height = 16777215
        self.setMouseTracking(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

        self._margin = BUBBLE_BORDER_WIDTH + 2
        self._live2d = Live2DWidget(parent=self, scale_multiplier=1.0)
        self._live2d.setMouseTracking(True)

        self._btn_chat = QPushButton("💬", self)
        self._btn_chat.setStyleSheet(_BTN_STYLE)
        self._btn_chat.setFixedSize(22, 22)
        self._btn_chat.setToolTip("打开/恢复对话窗与 AI 气泡窗")
        self._btn_chat.clicked.connect(self.chat_restore_requested.emit)
        self._btn_settings = QPushButton("⚙", self)
        self._btn_settings.setStyleSheet(_BTN_STYLE)
        self._btn_settings.setFixedSize(22, 22)
        self._btn_settings.setToolTip("设置")
        self._btn_settings.clicked.connect(self.settings_requested.emit)
        self._btn_min = QPushButton("—", self)
        self._btn_min.setStyleSheet(_BTN_STYLE)
        self._btn_min.setFixedSize(22, 22)
        self._btn_min.setToolTip("最小化")
        self._btn_min.clicked.connect(self.showMinimized)
        self._btn_close = QPushButton("✕", self)
        self._btn_close.setStyleSheet(_BTN_STYLE)
        self._btn_close.setFixedSize(22, 22)
        self._btn_close.setToolTip("关闭桌宠并退出程序")
        self._btn_close.clicked.connect(self._request_close)
        for btn in (self._btn_chat, self._btn_settings, self._btn_min, self._btn_close):
            btn.hide()

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(500)
        self._hover_timer.timeout.connect(self._hide_controls)

        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(80)
        self._cursor_timer.timeout.connect(self._poll_global_cursor)
        self._last_cursor_global: QPoint | None = None
        self._cursor_timer.start()

        self.setAcceptDrops(True)
        self._live2d.setAcceptDrops(True)
        self._drop_highlight = False

    @property
    def live2d(self) -> Live2DWidget:
        return self._live2d

    def apply_ui_prefs(self, prefs: PetUiPreferences) -> None:
        self._character_scale = clamp_character_scale(prefs.character_scale)
        self._custom_width = max(0, prefs.character_width_px)
        self._custom_height = max(0, prefs.character_height_px)
        self._live2d.set_scale_multiplier(self._character_scale)
        self._live2d.apply_render_prefs(
            fill_percent=prefs.fill_percent,
            crop_shrink_percent=prefs.crop_shrink_percent,
        )
        self._sync_frame_size()

    def set_character_scale(self, scale: float) -> None:
        self._character_scale = clamp_character_scale(scale)
        self._live2d.set_scale_multiplier(self._character_scale)

    def _sync_frame_size(self, base_width: int | None = None) -> None:
        """调整模型框（窗口）尺寸；不随人物大小缩放。"""
        aspect = self._live2d.content_aspect()
        if aspect <= 0:
            QTimer.singleShot(50, lambda: self._sync_frame_size(base_width))
            return
        base = base_width or DEFAULT_CHARACTER_WIDTH
        if self._custom_width > 0:
            body_w = max(80, self._custom_width)
        else:
            inner = self._inner_rect()
            if inner.width() >= 80:
                body_w = inner.width()
            else:
                body_w = max(80, base)
        if self._custom_height > 0:
            body_h = max(100, self._custom_height)
        else:
            inner = self._inner_rect()
            if inner.height() >= 100:
                body_h = inner.height()
            else:
                body_h = max(100, int(body_w * aspect))
        total_m = self._margin * 2
        self.resize(body_w + total_m, body_h + total_m)
        self._relayout()
        self._live2d.update()

    def fit_to_model(self, base_width: int | None = None) -> None:
        """模型加载或切换后：同步渲染缩放与模型框尺寸。"""
        self._live2d.set_scale_multiplier(self._character_scale)
        self._sync_frame_size(base_width)

    def _inner_rect(self) -> QRect:
        return self.rect().adjusted(
            self._margin, self._margin, -self._margin, -self._margin
        )

    def _character_hit_global(self) -> QRect:
        """人物本体在窗口坐标系下的区域。"""
        inner = self._inner_rect()
        crop = self._live2d.tight_crop_rect_local()
        return QRect(
            inner.x() + crop.x(),
            inner.y() + crop.y(),
            crop.width(),
            crop.height(),
        )

    def _over_chrome(self, pos: QPoint) -> bool:
        if any(self._edge_at(pos)):
            return True
        for btn in (self._btn_chat, self._btn_settings, self._btn_min, self._btn_close):
            if btn.isVisible() and btn.geometry().contains(pos):
                return True
        return False

    def _set_border_visible(self, visible: bool) -> None:
        if self._border_visible == visible:
            return
        self._border_visible = visible
        self.update()

    def _apply_click_through(self, enabled: bool) -> None:
        if self._click_through == enabled:
            return
        self._click_through = enabled
        set_click_through(self, enabled)

    def _sync_idle_render(self, *, active: bool) -> None:
        if active:
            if not self._cursor_timer.isActive():
                self._cursor_timer.start()
            self._live2d.start_loop()
        else:
            self._cursor_timer.stop()
            self._live2d.stop_loop()
            self._last_cursor_global = None
            self._live2d.clear_pointer()

    def _poll_global_cursor(self) -> None:
        if not self.isVisible() or self.isMinimized():
            self._hover_on_model = False
            self._set_border_visible(False)
            self._click_through = None
            set_click_through(self, False)
            self._last_cursor_global = None
            self._live2d.clear_pointer()
            return
        gpos = QCursor.pos()
        moved = (
            self._last_cursor_global is None
            or (gpos - self._last_cursor_global).manhattanLength() >= 3
        )
        if moved:
            self._last_cursor_global = gpos
            self._live2d.set_pointer_global(gpos)
        local = self.mapFromGlobal(gpos)

        if not self.rect().contains(local):
            self._hover_on_model = False
            self._set_border_visible(False)
            self._apply_click_through(False)
            return

        if any(self._edge_at(local)) or self._over_chrome(local):
            self._hover_on_model = False
            self._set_border_visible(False)
            self._apply_click_through(False)
            self._hover_timer.stop()
            self._show_controls()
            return
        on_model = self._character_hit_global().contains(local)
        self._hover_on_model = on_model
        self._set_border_visible(on_model)
        self._apply_click_through(not on_model)
        if on_model:
            self._hover_timer.stop()
            self._show_controls()

    def _relayout(self) -> None:
        inner = self._inner_rect()
        if inner.width() > 0 and inner.height() > 0:
            self._live2d.setGeometry(inner)
        x = self.width() - self._margin - 22
        y = self._margin + 2
        self._btn_close.move(x, y)
        self._btn_min.move(x - 24, y)
        self._btn_settings.move(x - 48, y)
        self._btn_chat.move(x - 72, y)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._drop_highlight:
            pen = QPen(QColor(59, 130, 246, 220))
            pen.setWidth(BUBBLE_BORDER_WIDTH + 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            hit = self._character_hit_global()
            painter.drawRect(hit.adjusted(1, 1, -1, -1))
        if not self._border_visible:
            painter.end()
            return
        pen = QPen(QColor(0, 0, 0))
        pen.setWidth(BUBBLE_BORDER_WIDTH)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = BUBBLE_BORDER_WIDTH // 2 + 1
        painter.drawRect(self.rect().adjusted(inset, inset, -inset, -inset))
        painter.end()

    def set_status_hint(self, text: str) -> None:
        """写入任务栏标题（人物窗无边框，界面上不可见）。"""
        self.setWindowTitle(f"14酱 · {text}"[:48])

    def can_accept_screenshot_input(self) -> bool:
        if not self.isVisible() or self.isMinimized():
            return False
        if self._hover_on_model:
            return True
        pos = self.mapFromGlobal(QCursor.pos())
        return self._inner_rect().contains(pos)

    def cursor_over_model(self) -> bool:
        if not self.isVisible() or self.isMinimized():
            return False
        pos = self.mapFromGlobal(QCursor.pos())
        return self._character_hit_global().contains(pos)

    def paste_screenshot_from_clipboard(self) -> bool:
        """剪贴板含图片时贴到人物（识图用）。返回是否已接收。"""
        img = image_from_clipboard()
        if img is None:
            return False
        self._on_model_drop_image(img)
        return True

    def _on_model_drop_image(self, img) -> None:
        if not isinstance(img, QImage) or img.isNull():
            return
        b64, mime = qimage_to_payload(img)
        if not b64:
            return
        self.screenshot_attached.emit(b64, mime)
        self._drop_highlight = False
        self.update()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if not mime_has_image(mime):
            event.ignore()
            return
        pos = event.position().toPoint()
        if not self._character_hit_global().contains(pos):
            event.ignore()
            return
        set_click_through(self, False)
        self._drop_highlight = True
        self.update()
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if not mime_has_image(mime):
            event.ignore()
            return
        pos = event.position().toPoint()
        over = self._character_hit_global().contains(pos)
        self._drop_highlight = over
        self.update()
        if over:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop_highlight = False
        self.update()
        self._poll_global_cursor()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if not self._character_hit_global().contains(pos):
            event.ignore()
            return
        img = image_from_mime(event.mimeData())
        if img is not None:
            self._on_model_drop_image(img)
            event.acceptProposedAction()
        else:
            event.ignore()
        self._poll_global_cursor()

    def _show_controls(self) -> None:
        self._btn_chat.show()
        self._btn_settings.show()
        self._btn_min.show()
        self._btn_close.show()

    def _hide_controls(self) -> None:
        self._btn_chat.hide()
        self._btn_settings.hide()
        self._btn_min.hide()
        self._btn_close.hide()

    def _try_begin_drag(self, global_pos: QPoint, local_pos: QPoint) -> bool:
        if not self._character_hit_global().contains(local_pos):
            return False
        if self._over_chrome(local_pos):
            return False
        self._drag_start = global_pos
        self._window_start = self.frameGeometry().topLeft()
        self._drag_active = True
        set_click_through(self, False)
        return True

    def _request_close(self) -> None:
        """关闭人物窗 = 退出桌宠（由 app 统一收尾，勿仅 hide）。"""
        self.closed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()
        self._live2d.update()

    def _apply_resize(self, global_pos: QPoint) -> None:
        set_click_through(self, False)
        EdgeResizeMixin._apply_resize(self, global_pos)

    def enterEvent(self, event) -> None:
        self._hover_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_timer.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()
        gpos = event.globalPosition().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            if self._try_begin_resize(gpos, pos):
                event.accept()
                return
            if self._try_begin_drag(gpos, pos):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        gpos = event.globalPosition().toPoint()
        if self._resize_active:
            self._apply_resize(gpos)
            return
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_drag(gpos)
            return
        self._on_resize_hover(pos)
        super().mouseMoveEvent(event)

    def _end_resize(self) -> None:
        was_active = self._resize_active
        EdgeResizeMixin._end_resize(self)
        if was_active:
            inner = self._inner_rect()
            self._custom_width = max(0, inner.width())
            self._custom_height = max(0, inner.height())
            self.size_changed_by_user.emit(self._custom_width, self._custom_height)

    def mouseReleaseEvent(self, event) -> None:
        self._end_resize()
        self._end_drag()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        pos = event.position().toPoint()
        if not self._character_hit_global().contains(pos):
            super().wheelEvent(event)
            return
        dy = event.angleDelta().y()
        if dy == 0:
            return
        step = CHARACTER_SCALE_SPIN_STEP_PERCENT / 100.0
        if dy < 0:
            step = -step
        self.set_character_scale(self._character_scale + step)
        self.scale_changed.emit(self._character_scale)
        event.accept()

    def closeEvent(self, event) -> None:
        # 任务栏关闭、Alt+F4；✕ 按钮走 _request_close → closed，此处避免重复退出
        if not getattr(self, "_pet_exiting", False):
            self.closed.emit()
        self._cursor_timer.stop()
        set_click_through(self, False)
        self._live2d.shutdown()
        event.accept()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_idle_render(active=not self.isMinimized())

    def hideEvent(self, event) -> None:
        self._sync_idle_render(active=False)
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_idle_render(active=self.isVisible() and not self.isMinimized())
