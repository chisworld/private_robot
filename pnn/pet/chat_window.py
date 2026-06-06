"""对话独立窗口：仅标题栏与输入，AI 文案由独立气泡窗显示。"""



from __future__ import annotations



from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget



from pnn.pet.fonts import make_font

from pnn.pet.frame_mixin import BORDER_WIDTH, DragMoveMixin, EdgeResizeMixin, FrameBorderMixin

from pnn.pet.icons import mic_icon, mic_icon_size

from pnn.pet.color_picker_widget import (
    bg_alpha_from_transparency_percent,
    hex_to_rgba_css,
    is_bg_fully_transparent,
    normalize_hex,
)

from pnn.pet.preferences import PetUiPreferences





class ChatWindow(QWidget, FrameBorderMixin, EdgeResizeMixin, DragMoveMixin):

    send_requested = Signal(str)

    mic_requested = Signal()

    closed = Signal()

    minimized_to_tray = Signal()

    focus_changed = Signal(bool)

    geometry_changed = Signal()



    def __init__(self, prefs: PetUiPreferences | None = None, parent: QWidget | None = None) -> None:

        super().__init__(parent)

        self._prefs = prefs or PetUiPreferences()

        self._mic_active = False

        self._mic_always_on = False

        self._geom_save_timer = QTimer(self)

        self._geom_save_timer.setSingleShot(True)

        self._geom_save_timer.setInterval(350)

        self._geom_save_timer.timeout.connect(self.geometry_changed.emit)

        self.setWindowTitle("14酱 · 对话")

        self.resize(360, 96)

        self.setMinimumSize(280, 88)

        self.setWindowFlags(

            Qt.WindowType.FramelessWindowHint

            | Qt.WindowType.Window

            | Qt.WindowType.WindowStaysOnTopHint,

        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.setAutoFillBackground(False)



        outer = QVBoxLayout(self)

        outer.setContentsMargins(

            BORDER_WIDTH + 4, BORDER_WIDTH + 4, BORDER_WIDTH + 4, BORDER_WIDTH + 4

        )

        outer.setSpacing(4)



        self._panel = QWidget()

        self._panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QVBoxLayout(self._panel)

        layout.setContentsMargins(2, 2, 2, 2)

        layout.setSpacing(4)



        self._title_bar = QWidget()

        self._title_bar.setFixedHeight(40)

        self._title_bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        title_row = QHBoxLayout(self._title_bar)

        title_row.setContentsMargins(4, 4, 4, 4)

        self._title = QLabel("对话")

        self._title.setToolTip("按住本行空白处拖动窗口（输入框区域除外）")

        title_row.addWidget(self._title)

        title_row.addStretch(1)

        self._btn_min = QPushButton("—")

        self._btn_min.setFixedSize(22, 22)

        self._btn_min.setToolTip("最小化到任务栏")

        self._btn_min.clicked.connect(self._on_minimize)

        title_row.addWidget(self._btn_min)

        self._btn_close = QPushButton("✕")

        self._btn_close.setFixedSize(22, 22)

        self._btn_close.setToolTip("关闭")

        self._btn_close.clicked.connect(self._request_close)

        title_row.addWidget(self._btn_close)

        layout.addWidget(self._title_bar)

        row = QHBoxLayout()

        self._input = QLineEdit()

        self._input.setPlaceholderText("")

        self._input.returnPressed.connect(self._on_send)

        row.addWidget(self._input)



        self._btn_mic = QPushButton()

        self._btn_mic.setFixedSize(32, 32)

        self._btn_mic.setIcon(mic_icon(active=False))

        self._btn_mic.setIconSize(mic_icon_size())

        self._btn_mic.setToolTip("点击开启常开麦克风：说完一句自动发给 AI (Ctrl+M)")

        self._btn_mic.clicked.connect(self.mic_requested.emit)

        row.addWidget(self._btn_mic)



        self._btn_send = QPushButton("→")

        self._btn_send.setFixedSize(30, 30)

        self._btn_send.clicked.connect(self._on_send)

        row.addWidget(self._btn_send)



        layout.addLayout(row)

        outer.addWidget(self._panel)

        self._apply_styles()



    def restore_geometry(self, prefs: PetUiPreferences) -> None:

        w = prefs.chat_window_w if prefs.chat_window_w > 0 else self.width()

        h = prefs.chat_window_h if prefs.chat_window_h > 0 else self.height()

        if prefs.chat_window_x >= 0 and prefs.chat_window_y >= 0:

            self.setGeometry(prefs.chat_window_x, prefs.chat_window_y, w, h)



    def capture_geometry(self) -> tuple[int, int, int, int]:

        g = self.geometry()

        return g.x(), g.y(), g.width(), g.height()



    def _schedule_geometry_save(self) -> None:

        self._geom_save_timer.start()



    def apply_preferences(self, prefs: PetUiPreferences) -> None:

        self._prefs = prefs

        self._apply_styles()



    def _apply_styles(self) -> None:

        size = self._prefs.chat_font_size
        text_color = normalize_hex(self._prefs.chat_text_color, fallback="#111827")
        text_qc = QColor(text_color)

        tp = self._prefs.chat_bg_transparency_percent

        panel_alpha = bg_alpha_from_transparency_percent(tp)

        fully_transparent = is_bg_fully_transparent(tp)

        self._draw_frame_border = not fully_transparent



        panel_bg = "transparent" if fully_transparent else hex_to_rgba_css(

            self._prefs.chat_bg_color,

            alpha=panel_alpha,

            fallback="#f8fafc",

        )

        font = make_font(self._prefs.chat_font_family, size)

        self._panel.setStyleSheet(

            f"background-color: {panel_bg}; border-radius: 8px;"

        )

        self._title_bar.setStyleSheet("background: transparent;")

        self._title.setFont(font)
        self._title.setStyleSheet(
            f"color: {text_color}; font-weight: 600; background: transparent;"
        )
        title_palette = self._title.palette()
        title_palette.setColor(QPalette.ColorRole.WindowText, text_qc)
        self._title.setPalette(title_palette)

        fam = font.family()

        if fully_transparent:

            input_bg = "transparent"

            input_border = "border: none;"

        else:

            input_bg = hex_to_rgba_css(

                self._prefs.chat_bg_color,

                alpha=panel_alpha,

                fallback="#ffffff",

            )

            input_border = "border: 1px solid rgba(0,0,0,0.25);"

        self._input.setStyleSheet(

            f"QLineEdit {{ {input_border}"

            f" background: {input_bg}; color: {text_color};"

            f" font-family: '{fam}'; font-size: {max(11, size - 2)}px;"

            f" border-radius: 12px; padding: 6px 10px; }}"

        )

        btn_style = (

            f"QPushButton {{ border: none; background: transparent; color: {text_color}; "

            "font-size: 14px; }"

            "QPushButton:hover { background: rgba(0,0,0,0.06); border-radius: 6px; }"

        )

        self._btn_send.setStyleSheet(btn_style)

        self._btn_min.setStyleSheet(btn_style)

        self._btn_close.setStyleSheet(btn_style)

        self._btn_mic.setStyleSheet(

            "QPushButton { border: none; background: transparent; border-radius: 8px; }"

            "QPushButton:hover { background: rgba(0,0,0,0.06); }"

        )

        self.set_asr_active(self._mic_active)



    def set_input_enabled(self, enabled: bool) -> None:

        self._input.setEnabled(enabled)

    def set_input_text(self, text: str) -> None:

        self._input.setText(text)



    def input_text(self) -> str:

        return self._input.text()



    def clear_asr_preview(self) -> None:

        """ASR 识别文字只显示在输入框。"""

        return



    def set_mic_always_on(self, enabled: bool) -> None:

        self._mic_always_on = enabled

        self._update_mic_ui()



    def set_asr_active(self, active: bool) -> None:

        self._mic_active = active

        self._update_mic_ui()



    def _update_mic_ui(self) -> None:

        self._btn_mic.setIcon(mic_icon(active=self._mic_active or self._mic_always_on))

        if self._mic_always_on:

            self._btn_mic.setToolTip(

                "常开麦克风中 · 说完自动发送 · 点击关闭 (Ctrl+M)"

                if self._mic_active

                else "常开已开 · 正在连接… · 点击关闭 (Ctrl+M)"

            )

            self._btn_mic.setStyleSheet(

                "QPushButton { border: none; background: rgba(34,197,94,0.15); "

                "border-radius: 8px; }"

                "QPushButton:hover { background: rgba(34,197,94,0.25); }"

            )

        else:

            self._btn_mic.setStyleSheet(

                "QPushButton { border: none; background: transparent; border-radius: 8px; }"

                "QPushButton:hover { background: rgba(0,0,0,0.06); }"

            )

            self._btn_mic.setToolTip(

                "点击开启常开麦克风：说完一句自动发给 AI (Ctrl+M)"

            )



    def _on_send(self) -> None:

        text = self._input.text().strip()

        if not text:

            return

        self._input.clear()

        self.send_requested.emit(text)



    def _on_minimize(self) -> None:

        self.showMinimized()

        self.minimized_to_tray.emit()



    def _request_close(self) -> None:

        self.closed.emit()

        self.close()



    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        try:
            from PySide6.QtCore import QEvent

            if event.type() == QEvent.Type.ActivationChange:
                self.focus_changed.emit(self.isActiveWindow())
        except Exception:
            pass

    def closeEvent(self, event) -> None:

        self.closed.emit()

        super().closeEvent(event)



    def _no_drag_widgets(self) -> tuple[QWidget, ...]:

        return (self._input, self._btn_mic, self._btn_send, self._btn_close, self._btn_min)



    def _is_interactive_at(self, pos: QPoint) -> bool:

        w = self.childAt(pos)

        while w and w is not self:

            if w in self._no_drag_widgets():

                return True

            w = w.parentWidget()

        return False



    def _can_drag_from(self, pos: QPoint) -> bool:

        if hasattr(self, "_edge_at") and any(self._edge_at(pos)):

            return False

        return not self._is_interactive_at(pos)



    def mousePressEvent(self, event) -> None:

        if event.button() == Qt.MouseButton.LeftButton:

            pos = event.position().toPoint()

            gpos = event.globalPosition().toPoint()

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



    def mouseReleaseEvent(self, event) -> None:

        was_drag = self._drag_active

        was_resize = self._resize_active

        self._end_resize()

        self._end_drag()

        if was_drag or was_resize:

            self._schedule_geometry_save()

        super().mouseReleaseEvent(event)

