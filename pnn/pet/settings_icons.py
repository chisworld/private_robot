"""设置界面导航图标 — Lucide 风格 + 渐变活动态渲染。"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Lucide-style 24×24 stroke icons (stroke-width 1.65, round caps)
_ICON_SVGS: dict[str, str] = {
    "layout": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
 stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">
  <rect width="18" height="18" x="3" y="3" rx="2.5"/>
  <path d="M3 9h18"/><path d="M9 21V9"/>
</svg>""",
    "user": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
 stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">
  <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>
  <circle cx="12" cy="7" r="4"/>
</svg>""",
    "brain": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
 stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/>
  <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/>
  <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/>
  <path d="M9 18h6"/>
</svg>""",
    "calendar": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
 stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">
  <path d="M8 2v4"/><path d="M16 2v4"/>
  <rect width="18" height="18" x="3" y="4" rx="2.5"/>
  <path d="M3 10h18"/>
</svg>""",
    "message": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
 stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">
  <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>
</svg>""",
    "wrench": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
 stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
</svg>""",
    "mic": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
 stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
  <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
  <line x1="12" x2="12" y1="19" y2="22"/>
</svg>""",
    "settings": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
 stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
  <circle cx="12" cy="12" r="3"/>
</svg>""",
}

# ── 活动态渐变色彩（图标使用的颜色） ──
ACTIVE_ICON_COLORS = ["#818cf8", "#a78bfa", "#6366f1"]
INACTIVE_ICON_COLOR = "#64748b"
HOVER_ICON_COLOR = "#94a3b8"


def _render_svg_pixmap(svg_content: str, size: int) -> QPixmap:
    """将 SVG 字符串渲染为 QPixmap。"""
    renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return pixmap


def _blend_svg_gradient(
    template: str, colors: list[str], size: int
) -> QPixmap:
    """将多个单色 SVG 叠加渲染以模拟渐变（朴素但有效）。"""
    if len(colors) == 1:
        svg = template.format(color=colors[0]).strip()
        return _render_svg_pixmap(svg, size)

    # Render base layer (primary color, full opacity)
    svg_base = template.format(color=colors[0]).strip()
    pixmap = _render_svg_pixmap(svg_base, size)

    # Overlay additional colors with decreasing opacity
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)

    for i, color in enumerate(colors[1:], start=1):
        alpha = max(0.15, 0.50 - i * 0.15)
        svg_overlay = template.format(color=color).strip()
        overlay = _render_svg_pixmap(svg_overlay, size)
        painter.setOpacity(alpha)
        painter.drawPixmap(0, 0, overlay)

    painter.end()
    return pixmap


def settings_icon(
    name: str,
    *,
    color: str = INACTIVE_ICON_COLOR,
    size: int = 18,
    active: bool = False,
) -> QIcon:
    """Render a named settings nav icon.

    Args:
        name: Icon key from _ICON_SVGS (layout, user, brain, calendar, message, wrench, mic).
        color: Fallback stroke color (used when active=False).
        size: Icon size in pixels.
        active: If True, render with gradient overlay instead of flat color.
    """
    template = _ICON_SVGS.get(name, _ICON_SVGS["settings"])

    if active:
        pixmap = _blend_svg_gradient(template, ACTIVE_ICON_COLORS, size)
    else:
        svg = template.format(color=color).strip()
        pixmap = _render_svg_pixmap(svg, size)

    icon = QIcon(pixmap)
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.On)
    return icon
