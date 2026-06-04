"""按对话框可视区域分页显示长文本。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QLabel


def _split_pages(text: str, font: QFont, width: int, max_height: int) -> list[str]:
    if not text.strip() or width < 40 or max_height < 12:
        return [text] if text else []

    fm = QFontMetrics(font)
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        start = 0
        while start < len(para):
            remaining = para[start:]
            # 二分找最长可放下的一行
            lo, hi = 1, len(remaining)
            best = 1
            while lo <= hi:
                mid = (lo + hi) // 2
                chunk = remaining[:mid]
                br = fm.boundingRect(0, 0, width, 10000, Qt.TextFlag.TextWordWrap, chunk)
                if br.height() <= fm.lineSpacing() + 2:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            lines.append(remaining[:best])
            start += best

    pages: list[str] = []
    buf: list[str] = []
    used_h = 0
    line_h = fm.height() + 2
    for line in lines:
        if used_h + line_h > max_height and buf:
            pages.append("\n".join(buf))
            buf = []
            used_h = 0
        buf.append(line)
        used_h += line_h
    if buf:
        pages.append("\n".join(buf))
    return pages if pages else [text]


def _fit_tail(text: str, font: QFont, width: int, max_height: int) -> str:
    pages = _split_pages(text, font, width, max_height)
    return pages[-1] if pages else text


class BubbleTextPager:
    """超出高度则分页；流式时只显示当前能放下的一段尾部。"""

    def __init__(self, label: QLabel, interval_ms: int = 2800) -> None:
        self._label = label
        self._interval_ms = interval_ms
        self._pages: list[str] = []
        self._index = 0
        self._stream_cache = ""
        self._timer = QTimer(label)
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._on_tick)

    def set_interval(self, ms: int) -> None:
        self._interval_ms = max(800, min(15000, ms))

    def stop(self) -> None:
        self._timer.stop()
        self._pages = []
        self._index = 0

    def _metrics(self) -> tuple[QFont, int, int]:
        font = self._label.font()
        w = max(40, self._label.width() - 4)
        max_h = max(24, self._label.maximumHeight())
        if max_h >= 10000:
            max_h = max(24, self._label.height())
        return font, w, max_h

    def _notify_parent_repaint(self) -> None:
        parent = self._label.parentWidget()
        if parent is not None:
            parent.update()

    def show_stream(self, text: str) -> None:
        """流式更新：只显示能放进对话框的最后一段。"""
        self._timer.stop()
        if not text.strip():
            self._stream_cache = ""
            self._label.clear()
            self._notify_parent_repaint()
            return
        font, w, max_h = self._metrics()
        shown = _fit_tail(text, font, w, max_h)
        if shown == self._stream_cache:
            return
        self._stream_cache = shown
        self._label.setText(shown)
        self._label.show()
        self._notify_parent_repaint()

    def show_paged(self, text: str) -> None:
        """完整回复：分页轮播，满页后清空再显示下一页。"""
        self._timer.stop()
        if not text.strip():
            self._label.clear()
            self._notify_parent_repaint()
            return
        font, w, max_h = self._metrics()
        pages = _split_pages(text, font, w, max_h)
        if len(pages) <= 1:
            self._label.setText(text)
            self._label.show()
            self._notify_parent_repaint()
            return
        self._pages = pages
        self._index = 0
        self._label.setText(pages[0])
        self._label.show()
        self._notify_parent_repaint()
        self._index = 1
        if len(pages) > 1:
            self._timer.start(self._interval_ms)

    def _show_page(self) -> None:
        if self._index >= len(self._pages):
            self._timer.stop()
            return
        self._label.setText(self._pages[self._index])
        self._label.show()
        self._notify_parent_repaint()

    def _on_tick(self) -> None:
        if self._index >= len(self._pages):
            self._timer.stop()
            return
        self._show_page()
        self._index += 1
