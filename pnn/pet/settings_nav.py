"""设置窗左侧导航栏。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QPushButton, QVBoxLayout, QWidget

from pnn.pet.settings_icons import settings_icon


@dataclass(frozen=True)
class SettingsNavItem:
    nav_id: str
    label: str
    icon: str
    subtitle: str = ""


SETTINGS_NAV_ITEMS: tuple[SettingsNavItem, ...] = (
    SettingsNavItem("ui", "界面", "layout", "窗口、气泡与显示偏好"),
    SettingsNavItem("character", "角色", "user", "角色包、缩放与裁剪"),
    SettingsNavItem("memory", "记忆", "brain", "长期记忆与提取策略"),
    SettingsNavItem("presence", "日程", "calendar", "空闲搭话、番茄与提醒"),
    SettingsNavItem("llm", "对话", "message", "LLM 提供商与模型"),
    SettingsNavItem("tools", "工具", "wrench", "MCP、快捷启动与本机助手"),
    SettingsNavItem("voice", "语音", "mic", "TTS 合成与 ASR 识别"),
)


class SettingsNavRail(QFrame):
    """左侧图标 + 文字导航。"""

    item_selected = Signal(int)

    def __init__(self, items: tuple[SettingsNavItem, ...] = SETTINGS_NAV_ITEMS, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsNavRail")
        self._items = items
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        for index, item in enumerate(items):
            btn = QPushButton(item.label)
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setIcon(settings_icon(item.icon, color="#8E8E93", size=17))
            btn.setIconSize(QSize(17, 17))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("navIndex", index)
            btn.clicked.connect(lambda _checked, idx=index: self._on_btn(idx))
            self._group.addButton(btn, index)
            self._buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch(1)
        if self._buttons:
            self._buttons[0].setChecked(True)
            self._style_active(0)

    def _on_btn(self, index: int) -> None:
        self._style_active(index)
        self.item_selected.emit(index)

    def _style_active(self, index: int) -> None:
        for i, btn in enumerate(self._buttons):
            active = i == index
            item = self._items[i]
            color = "#007AFF" if active else "#8E8E93"
            btn.setIcon(settings_icon(item.icon, color=color, size=17))
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_current_index(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)
            self._style_active(index)

    def item_at(self, index: int) -> SettingsNavItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None
