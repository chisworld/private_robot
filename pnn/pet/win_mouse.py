"""Windows 窗口鼠标穿透（透明区域不挡桌面操作）。"""

from __future__ import annotations

import sys
from ctypes import windll, wintypes

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020


def _hwnd(widget) -> int:
    wid = int(widget.winId())
    if wid == 0:
        return 0
    if sys.platform == "win32":
        try:
            return int(windll.user32.GetAncestor(wid, 2))  # GA_ROOT
        except Exception:
            return wid
    return wid


def set_click_through(widget, enabled: bool) -> None:
    """enabled=True 时鼠标事件穿透到下层窗口。"""
    if sys.platform != "win32":
        return
    hwnd = _hwnd(widget)
    if not hwnd:
        return
    try:
        style = windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception:
        pass
