"""写作/IDE 前台检测。"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_IDE_TITLE_RE = re.compile(
    r"(?:"
    r"Visual Studio Code|Cursor|PyCharm|IntelliJ|WebStorm|CLion|"
    r"devenv|Android Studio|Sublime Text|Notepad\+\+|"
    r"\.(?:py|ts|tsx|js|jsx|java|go|rs|cpp|c|h|md|txt)\s*[-–—]"
    r")",
    re.IGNORECASE,
)

_WRITING_TITLE_RE = re.compile(
    r"(?:Word|WPS|Writer|Typora|Obsidian|Notion|语雀|飞书文档|腾讯文档)",
    re.IGNORECASE,
)


def _foreground_window_title() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return (buf.value or "").strip()
    except Exception:
        return ""


def is_ide_or_writing_foreground() -> tuple[bool, str]:
    title = _foreground_window_title()
    if not title:
        return False, ""
    if _IDE_TITLE_RE.search(title):
        return True, title
    if _WRITING_TITLE_RE.search(title):
        return True, title
    return False, title


class WritingIdleTracker:
    def __init__(self, *, idle_minutes: int = 8) -> None:
        self._idle_minutes = max(3, int(idle_minutes))
        self._last_activity_at = datetime.now()
        self._last_nudge_at: datetime | None = None

    def set_idle_minutes(self, minutes: int) -> None:
        self._idle_minutes = max(3, int(minutes))

    def touch_user_activity(self) -> None:
        self._last_activity_at = datetime.now()

    def should_nudge(self, *, cooldown_seconds: int = 600) -> bool:
        active, _title = is_ide_or_writing_foreground()
        if not active:
            return False
        now = datetime.now()
        if (now - self._last_activity_at).total_seconds() < self._idle_minutes * 60:
            return False
        if self._last_nudge_at and (now - self._last_nudge_at).total_seconds() < cooldown_seconds:
            return False
        self._last_nudge_at = now
        return True
