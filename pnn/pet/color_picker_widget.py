"""色块 + 取色器行控件。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

# (显示名, 十六进制)
COLOR_PRESETS: list[tuple[str, str]] = [
    ("墨黑", "#111827"),
    ("纯白", "#ffffff"),
    ("纯黑", "#000000"),
    ("深蓝", "#1e40af"),
    ("朱红", "#dc2626"),
    ("翠绿", "#059669"),
    ("紫色", "#7c3aed"),
    ("橙色", "#ea580c"),
    ("灰色", "#64748b"),
    ("粉色", "#db2777"),
]


def bg_alpha_from_transparency_percent(percent: int) -> float:
    """0% = 不透明，100% = 完全透明。"""
    return max(0.0, min(1.0, (100 - int(percent)) / 100.0))


def is_bg_fully_transparent(percent: int) -> bool:
    return int(percent) >= 100


def hex_to_rgba_css(hex_color: str, *, alpha: float = 1.0, fallback: str = "#ffffff") -> str:
    """将 #RRGGBB 转为 CSS rgba(...)。"""
    c = QColor(normalize_hex(hex_color, fallback=fallback))
    a = max(0.0, min(1.0, alpha))
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {a})"


def normalize_hex(value: str, *, fallback: str = "#111827") -> str:
    raw = (value or fallback).strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 6:
        try:
            int(raw, 16)
            return f"#{raw.lower()}"
        except ValueError:
            pass
    return fallback


def contrast_text_color(bg_hex: str, *, prefer_dark: str = "#111827", prefer_light: str = "#ffffff") -> str:
    """根据背景亮度返回可读的文字色。"""
    bg = QColor(normalize_hex(bg_hex, fallback=prefer_dark))
    return prefer_light if bg.lightness() < 140 else prefer_dark


class _SwatchButton(QPushButton):
    """色块：直接写 background-color（避免父级 QSS 盖掉 QPalette）。"""

    def __init__(self, hx: str, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hx = normalize_hex(hx)
        self._selected = False
        self.setFixedSize(28, 28)
        self.setFlat(True)
        self.setToolTip(f"{name} {self._hx}")
        self.setProperty("hex", self._hx)
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        border = "2px solid #3b82f6" if selected else "1px solid #cbd5e1"
        self.setStyleSheet(
            f"background-color: {self._hx}; border: {border}; border-radius: 6px;"
        )


class ColorPickerRow(QWidget):
    """预设色块 + 当前色预览 + 系统取色对话框。"""

    color_changed = Signal(str)

    def __init__(self, initial: str = "#111827", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hex = normalize_hex(initial)
        self._swatches: list[_SwatchButton] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._preview = QLabel()
        self._preview.setFixedSize(36, 28)
        self._preview.setToolTip("当前颜色")
        root.addWidget(self._preview)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        for i, (name, hx) in enumerate(COLOR_PRESETS):
            btn = _SwatchButton(hx, name)
            btn.clicked.connect(self._on_swatch)
            btn.set_selected(hx.lower() == self._hex.lower())
            self._swatches.append(btn)
            grid.addWidget(btn, i // 5, i % 5)
        root.addWidget(grid_host, stretch=1)

        self._hex_label = QLabel(self._hex)
        self._hex_label.setObjectName("hexLabel")
        self._hex_label.setMinimumWidth(64)
        self._hex_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._hex_label)

        more = QPushButton("更多…")
        more.setObjectName("ghostBtn")
        more.setFixedHeight(28)
        more.clicked.connect(self._open_dialog)
        root.addWidget(more)

        self._refresh_preview()

    def hex_color(self) -> str:
        return self._hex

    def set_hex_color(self, value: str) -> None:
        self._hex = normalize_hex(value, fallback=self._hex)
        self._refresh_preview()
        self._update_swatch_selection()

    def _on_swatch(self) -> None:
        btn = self.sender()
        if not isinstance(btn, _SwatchButton):
            return
        hx = btn.property("hex")
        if hx:
            self.set_hex_color(str(hx))
            self.color_changed.emit(self._hex)

    def _open_dialog(self) -> None:
        start = QColor(self._hex)
        picked = QColorDialog.getColor(start, self, "选择颜色")
        if picked.isValid():
            self.set_hex_color(picked.name())
            self.color_changed.emit(self._hex)

    def _refresh_preview(self) -> None:
        self._hex_label.setText(self._hex)
        text_color = contrast_text_color(self._hex)
        self._preview.setStyleSheet(
            f"background-color: {self._hex}; color: {text_color};"
            "border: 1px solid #cbd5e1; border-radius: 6px;"
            "font-size: 11px; font-weight: 600;"
        )
        self._preview.setText("Aa")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _update_swatch_selection(self) -> None:
        for btn in self._swatches:
            hx = str(btn.property("hex") or "")
            btn.set_selected(hx.lower() == self._hex.lower())
