"""角色旁对话气泡：深灰圆角矩形（无左侧尖角）。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from pnn.pet.color_picker_widget import (
    bg_alpha_from_transparency_percent,
    contrast_text_color,
    is_bg_fully_transparent,
    normalize_hex,
)
from pnn.pet.fonts import make_font
from pnn.pet.text_pager import _split_pages

_PAD_H = 14
_PAD_V = 10
_RADIUS = 12
_DEFAULT_BUBBLE_BG = "#333333"
_THINKING_TEXT = frozenset({"…", "...", "⋯"})


def parse_text_color(value: str, *, fallback: str = "#FFFFFF") -> QColor:
    return _parse_color(value, fallback=fallback)


def _parse_color(value: str, *, fallback: str) -> QColor:
    raw = (value or fallback).strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 6:
        try:
            return QColor(int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
        except ValueError:
            pass
    return QColor(fallback) if fallback else QColor(255, 255, 255)


def _border_color_for(bg: QColor) -> QColor:
    return QColor(
        max(0, bg.red() - 11),
        max(0, bg.green() - 11),
        max(0, bg.blue() - 11),
    )


class SpeechBubble(QWidget):
    """绘制漫画式对话框；flexible 模式用于独立气泡窗。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        flexible: bool = False,
        font_size: int = 13,
        width_px: int = 120,
        height_px: int = 200,
        text_color: str = "#FFFFFF",
        bg_color: str = _DEFAULT_BUBBLE_BG,
        bg_transparency_percent: int = 0,
        page_interval_ms: int = 2000,
        font_family: str = "Microsoft YaHei UI",
        use_imported_font: bool = False,
        imported_family: str = "",
    ) -> None:
        super().__init__(parent)
        self._flexible = flexible
        self._font_family = font_family
        self._use_imported_font = use_imported_font
        self._imported_family = imported_family
        self._font_size = font_size
        self._width_px = width_px
        self._height_px = height_px
        self._text_color = text_color
        self._bg_color = bg_color
        self._bg_transparency_percent = bg_transparency_percent
        self._page_interval_ms = page_interval_ms
        self._text_color_q = parse_text_color(text_color)
        self._bg_color_q = _parse_color(bg_color, fallback=_DEFAULT_BUBBLE_BG)
        self._display_text = ""
        self._full_body = ""
        self._pages: list[str] = []
        self._page_index = 0
        self._streaming = False
        self._page_timer = QTimer(self)
        self._page_timer.timeout.connect(self._on_page_tick)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if not flexible:
            self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self._apply_geometry_and_style()
        self.hide()

    def apply_prefs(
        self,
        *,
        font_size: int,
        width_px: int,
        height_px: int,
        text_color: str,
        bg_color: str = _DEFAULT_BUBBLE_BG,
        bg_transparency_percent: int,
        page_interval_ms: int,
        font_family: str = "Microsoft YaHei UI",
        use_imported_font: bool = False,
        imported_family: str = "",
    ) -> None:
        self._font_family = font_family
        self._use_imported_font = use_imported_font
        self._imported_family = imported_family
        self._font_size = max(10, min(36, font_size))
        self._width_px = max(60, min(400, width_px))
        self._height_px = max(40, min(500, height_px))
        self._bg_color = normalize_hex(bg_color, fallback=_DEFAULT_BUBBLE_BG)
        self._bg_color_q = _parse_color(self._bg_color, fallback=_DEFAULT_BUBBLE_BG)
        self._text_color = normalize_hex(text_color, fallback="#ffffff")
        self._text_color_q = _parse_color(self._text_color, fallback="#ffffff")
        self._bg_transparency_percent = max(0, min(100, bg_transparency_percent))
        self._page_interval_ms = max(800, min(15000, page_interval_ms))
        self._apply_geometry_and_style()
        if self._full_body:
            self.set_text(self._full_body, stream=self._streaming)

    def set_font_size(self, size: int) -> None:
        self.apply_prefs(
            font_size=size,
            width_px=self._width_px,
            height_px=self._height_px,
            text_color=self._text_color,
            bg_color=self._bg_color,
            bg_transparency_percent=self._bg_transparency_percent,
            page_interval_ms=self._page_interval_ms,
        )

    def _body_font(self) -> QFont:
        return make_font(
            self._font_family,
            self._font_size,
            use_imported=self._use_imported_font,
            imported_family=self._imported_family,
        )

    def _split_body_pages(self, body: str) -> list[str]:
        font = self._body_font()
        rect = self._text_rect()
        pages = _split_pages(body, font, rect.width(), rect.height())
        return pages if pages else ([body] if body else [])

    def _stop_paging(self) -> None:
        self._page_timer.stop()
        self._pages = []
        self._page_index = 0

    def _show_page(self, index: int) -> None:
        if not self._pages:
            return
        self._page_index = index % len(self._pages)
        self._display_text = self._pages[self._page_index]
        self.show()
        if not self._flexible:
            self.raise_()
        self.update()

    def _start_paging(self, pages: list[str]) -> None:
        self._pages = pages
        self._page_index = 0
        self._show_page(0)
        if len(pages) <= 1:
            self._stop_paging()
            return
        self._page_index = 1
        self._page_timer.start(self._page_interval_ms)

    def _on_page_tick(self) -> None:
        if self._streaming or not self._pages:
            self._page_timer.stop()
            return
        if self._page_index >= len(self._pages):
            self._page_timer.stop()
            return
        self._show_page(self._page_index)
        self._page_index += 1

    def _apply_body_layout(self, body: str, *, stream: bool) -> None:
        self._streaming = stream
        self._full_body = body
        pages = self._split_body_pages(body)
        self._pages = pages
        if stream:
            self._page_timer.stop()
            # 流式：显示第一页并从顶部排版，避免短句贴底、上方大块空白
            self._display_text = pages[0] if pages else body
        elif len(pages) > 1:
            self._start_paging(pages)
        else:
            self._stop_paging()
            self._display_text = pages[0] if pages else body
        self.show()
        if not self._flexible:
            self.raise_()
        self.update()
        if stream:
            self.repaint()
        elif len(pages) > 1:
            return

    def _is_thinking_text(self, text: str) -> bool:
        return (text or "").strip() in _THINKING_TEXT

    def _thinking_font(self) -> QFont:
        size = max(28, min(52, int(self._font_size * 1.65)))
        return make_font(
            self._font_family,
            size,
            use_imported=self._use_imported_font,
            imported_family=self._imported_family,
        )

    def set_text(self, text: str, *, stream: bool = False) -> None:
        body = (text or "").strip()
        if not body:
            self.clear()
            return
        if self._is_thinking_text(body):
            self._streaming = False
            self._stop_paging()
            self._full_body = "…"
            self._display_text = "…"
            self.show()
            if not self._flexible:
                self.raise_()
            self.update()
            return
        self._apply_body_layout(body, stream=stream)

    def clear(self) -> None:
        self._stop_paging()
        self._streaming = False
        self._display_text = ""
        self._full_body = ""
        self.hide()
        self.update()

    def on_viewport_resized(self) -> None:
        if not self._flexible or not self._full_body:
            return
        self._apply_body_layout(self._full_body, stream=self._streaming)

    def text(self) -> str:
        return self._display_text

    def body_text(self) -> str:
        return self._full_body

    def page_count(self) -> int:
        if self._pages:
            return len(self._pages)
        return 1 if self._full_body else 0

    def suggested_read_ms(self) -> int:
        """无语音播放时，留给分页阅读的停留时间。"""
        n = self.page_count()
        if n <= 1:
            return 1200
        return max(2000, n * self._page_interval_ms)

    def _text_rect(self) -> QRect:
        if self._flexible:
            return QRect(
                _PAD_H,
                _PAD_V,
                max(20, self.width() - _PAD_H * 2),
                max(20, self.height() - _PAD_V * 2),
            )
        return QRect(
            _PAD_H,
            _PAD_V,
            max(20, self._width_px - _PAD_H * 2),
            max(20, self._height_px - _PAD_V * 2),
        )

    def _apply_geometry_and_style(self) -> None:
        if self._flexible:
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            return
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(self._width_px, self._height_px)

    def _bubble_body_rect(self) -> QRectF:
        if self._flexible:
            w, h = self.width(), self.height()
        else:
            w, h = self._width_px, self._height_px
        return QRectF(0.5, 0.5, w - 1, h - 1)

    def _draw_background(self, painter: QPainter) -> None:
        if not self._display_text:
            return
        if is_bg_fully_transparent(self._bg_transparency_percent):
            return
        alpha = int(255 * bg_alpha_from_transparency_percent(self._bg_transparency_percent))
        if alpha <= 0:
            return

        body = self._bubble_body_rect()
        path = QPainterPath()
        path.addRoundedRect(body, _RADIUS, _RADIUS)

        bg = QColor(self._bg_color_q)
        bg.setAlpha(alpha)
        border = _border_color_for(bg)
        border.setAlpha(min(255, alpha + 10))
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawPath(path)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        display = self._display_text
        if not display:
            painter.end()
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._draw_background(painter)
        painter.setPen(self._text_color_q)
        if self._is_thinking_text(display):
            painter.setFont(self._thinking_font())
            align = int(
                Qt.AlignmentFlag.AlignHCenter
                | Qt.AlignmentFlag.AlignVCenter
            )
        else:
            painter.setFont(self._body_font())
            align = int(
                Qt.AlignmentFlag.AlignHCenter
                | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextWordWrap
            )
        painter.drawText(QRectF(self._text_rect()), align, display)
        painter.end()
