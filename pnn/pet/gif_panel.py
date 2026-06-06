"""GIF 动作选择面板：显示 GIF 缩略图，点击触发 Live2D 表情/动作。"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QMovie, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pnn.pet.fonts import make_font

logger = logging.getLogger(__name__)

THUMB_SIZE = 120
PANEL_MIN_W = 320


class GifActionPanel(QFrame):
    """浮动面板：展示模型目录下的 GIF 动作预览，点击触发。"""

    action_triggered = Signal(str, str)  # gif_name, expression_name
    closed = Signal()

    def __init__(self, model_dir: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model_dir = Path(model_dir)
        self._motions: list[dict] = []
        self._thumb_labels: list[QLabel] = []

        self.setWindowTitle("动作预览")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setStyleSheet("QFrame { background: #1a1a2e; border: 2px solid #e94560; border-radius: 8px; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 标题
        title = QLabel("🎬 GIF 动作预览")
        title.setFont(make_font("Microsoft YaHei UI", 10))
        title.setStyleSheet("color: #e94560; padding: 2px 4px; border: none; background: transparent; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 提示
        hint = QLabel("点击缩略图触发动作")
        hint.setFont(make_font("Microsoft YaHei UI", 8))
        hint.setStyleSheet("color: #888; padding: 1px 4px; border: none; background: transparent;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent; border: none;")
        self._grid = QGridLayout(scroll_widget)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(6)
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        self.setMinimumWidth(PANEL_MIN_W)
        self.resize(PANEL_MIN_W + 20, 400)

        # 延迟加载
        QTimer.singleShot(50, self._load_gifs)

    def _load_gifs(self) -> None:
        from pnn.pet.gif_motions import discover_gif_motions

        try:
            self._motions = discover_gif_motions(self._model_dir)
        except Exception as exc:
            logger.warning("加载 GIF 动作失败: %s", exc)
            return

        # 清除旧缩略图
        for lbl in self._thumb_labels:
            lbl.deleteLater()
        self._thumb_labels.clear()

        cols = max(2, (self.width() - 30) // (THUMB_SIZE + 10))
        for i, motion in enumerate(self._motions):
            gif_path = Path(motion["path"])
            if not gif_path.is_file():
                continue

            row = i // cols
            col = i % cols

            container = QWidget()
            container.setStyleSheet("background: #16213e; border: 1px solid #333; border-radius: 4px;")
            container.setCursor(Qt.CursorShape.PointingHandCursor)
            container.setToolTip(
                f"{motion['display']}\n→ {motion['expression'] or '(基础动画)'}"
            )

            c_layout = QVBoxLayout(container)
            c_layout.setContentsMargins(2, 2, 2, 2)
            c_layout.setSpacing(2)

            # GIF 缩略图
            thumb = QLabel()
            thumb.setFixedSize(THUMB_SIZE, THUMB_SIZE)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet("border: none; background: #0f0f23;")

            movie = QMovie(str(gif_path))
            movie.setScaledSize(thumb.size())
            thumb.setMovie(movie)
            movie.start()

            # 标签
            label = QLabel(motion["display"])
            label.setFont(make_font("Microsoft YaHei UI", 8))
            label.setStyleSheet("color: #ccc; padding: 1px 2px; border: none; background: transparent;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            c_layout.addWidget(thumb)
            c_layout.addWidget(label)

            # 点击事件：用 mouseReleaseEvent 比 mousePressEvent 更安全
            gif_name = motion["name"]
            expr_name = motion["expression"]

            def make_handler(gif_n: str, expr_n: str) -> object:
                def handler(_event=None, g=gif_n, e=expr_n):
                    self.action_triggered.emit(g, e)
                return handler

            container.mouseReleaseEvent = make_handler(gif_name, expr_name)  # type: ignore[assignment]

            self._grid.addWidget(container, row, col)
            self._thumb_labels.append(thumb)

    def refresh(self) -> None:
        """重新加载 GIF 列表。"""
        self._load_gifs()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._motions:
            self._load_gifs()
