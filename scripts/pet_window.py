"""PySide6 桌面宠物窗口。

默认使用不透明窗口 + 深色背景（Windows 上最稳定）。
透明抠图模式需设置环境变量 PET_TRANSPARENT=1（依赖桌面截图，易白屏）。
"""

from __future__ import annotations

import base64
import os
import sys

from PySide6.QtCore import Qt, QUrl, QPoint, QEvent, QTimer, QBuffer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEnginePage,
)
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtGui import QColor, QSurfaceFormat, QPixmap

# 由 API 8765 托管静态页（/static），不依赖 Next 3000，避免 Pixi 脚本 404 / 白屏
PET_URL = os.environ.get("PET_URL", "http://127.0.0.1:8765/static/pet-desktop.html")
WINDOW_WIDTH = 360
WINDOW_HEIGHT = 640
BG_COLOR = QColor(15, 23, 42)  # slate-900，与网页 embed 背景一致

CAPTURE_INTERVAL_MS = 250


class PetPage(QWebEnginePage):
    """自动授予麦克风权限。"""

    def __init__(self, profile: QWebEngineProfile, parent: QWidget | None = None) -> None:
        super().__init__(profile, parent)

    def featurePermissionRequested(
        self, _origin: QUrl, feature: QWebEnginePage.Feature
    ) -> None:
        if feature in (
            QWebEnginePage.Feature.MediaAudioCapture,
            QWebEnginePage.Feature.MediaVideoCapture,
        ):
            self.setFeaturePermission(
                _origin,
                feature,
                QWebEnginePage.PermissionPolicy.PermissionGrantedByUser,
            )
        else:
            super().featurePermissionRequested(_origin, feature)


class PetWindow(QWidget):
    def __init__(self, *, transparent: bool = False) -> None:
        super().__init__()
        self._transparent = transparent

        self.setWindowTitle("14酱")
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        if transparent:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setObjectName("PetWindow")
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setStyleSheet("#PetWindow { background: transparent; border: none; }")
        else:
            self.setObjectName("PetWindowOpaque")
            self.setStyleSheet(
                f"#PetWindowOpaque {{ background: rgb({BG_COLOR.red()},"
                f"{BG_COLOR.green()},{BG_COLOR.blue()}); border: none; }}"
            )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        profile = QWebEngineProfile.defaultProfile()
        settings = profile.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False
        )
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )

        page = PetPage(profile)
        page.setBackgroundColor(QColor(0, 0, 0, 0) if transparent else BG_COLOR)
        page.loadFinished.connect(self._on_load_finished)

        self._webview = QWebEngineView()
        self._webview.setObjectName("PetWebView")
        self._webview.setPage(page)
        if transparent:
            self._webview.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self._webview.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            self._webview.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
            self._webview.setAutoFillBackground(False)
            self._webview.setStyleSheet("#PetWebView { background: transparent; }")
        else:
            self._webview.setStyleSheet(
                f"#PetWebView {{ background: rgb({BG_COLOR.red()},"
                f"{BG_COLOR.green()},{BG_COLOR.blue()}); }}"
            )
        self._webview.setMinimumSize(WINDOW_WIDTH, WINDOW_HEIGHT)

        page.renderProcessTerminated.connect(self._on_render_terminated)
        self._webview.installEventFilter(self)

        layout.addWidget(self._webview)
        self._webview.load(QUrl(PET_URL))

        self._capture_timer: QTimer | None = None
        if transparent:
            self._capture_timer = QTimer(self)
            self._capture_timer.setInterval(CAPTURE_INTERVAL_MS)
            self._capture_timer.timeout.connect(self._update_background)
            self._capture_timer.start()

        self._drag_start: QPoint | None = None
        self._window_start: QPoint | None = None
        self._drag_active = False
        self._page_ready = False

    def _on_load_finished(self, ok: bool) -> None:
        self._page_ready = ok
        if ok and self._transparent:
            self._update_background()

    def _capture_desktop(self) -> str:
        screen = QApplication.primaryScreen()
        if screen is None:
            return ""
        geom = self.frameGeometry()
        pixmap = screen.grabWindow(0, geom.x(), geom.y(), geom.width(), geom.height())
        if pixmap.isNull():
            return ""
        ba = QBuffer()
        ba.open(QBuffer.OpenModeFlag.WriteOnly)
        pixmap.save(ba, "PNG")
        return "data:image/png;base64," + base64.b64encode(ba.data()).decode()

    def _update_background(self) -> None:
        if not self._page_ready or not self._transparent:
            return
        try:
            data_url = self._capture_desktop()
            if not data_url or len(data_url) < 200:
                return
            js = (
                "(function(){"
                "var s=document.getElementById('pet-bg');"
                "if(!s){s=document.createElement('style');s.id='pet-bg';"
                "document.body.appendChild(s);}"
                f"s.textContent='body{{background-image:url({data_url})!important;"
                f"background-size:{WINDOW_WIDTH}px {WINDOW_HEIGHT}px!important;"
                "background-position:0 0!important;background-repeat:no-repeat!important;}}';"
                "})()"
            )
            self._webview.page().runJavaScript(js)
        except Exception:
            pass

    def _on_render_terminated(
        self,
        termination_status: QWebEnginePage.RenderProcessTerminationStatus,
        exit_code: int,
    ) -> None:
        print(
            f"[pet] 渲染进程退出 (status={int(termination_status)}, "
            f"code={exit_code})，1 秒后重载…"
        )
        QTimer.singleShot(1000, lambda: self._webview.reload())

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self._transparent:
            self._update_background()

    def eventFilter(self, watched, event) -> bool:
        if watched is not self._webview:
            return super().eventFilter(watched, event)

        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_start = event.globalPosition().toPoint()
                self._window_start = self.frameGeometry().topLeft()
                self._drag_active = False
                return False

        if event.type() == QEvent.Type.MouseMove:
            if (
                self._drag_start is not None
                and self._window_start is not None
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                delta = event.globalPosition().toPoint() - self._drag_start
                if not self._drag_active:
                    if abs(delta.x()) > 6 or abs(delta.y()) > 6:
                        self._drag_active = True
                if self._drag_active:
                    self.move(self._window_start + delta)
                    return True

        if event.type() == QEvent.Type.MouseButtonRelease:
            was_drag = self._drag_active
            self._drag_start = None
            self._window_start = None
            self._drag_active = False
            if was_drag:
                return True

        return super().eventFilter(watched, event)


def main() -> None:
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    for part in (
        "--use-fake-ui-for-media-stream",
        "--enable-webgl",
        "--ignore-gpu-blocklist",
    ):
        if part not in flags:
            flags = f"{flags} {part}".strip()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags

    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    transparent = os.environ.get("PET_TRANSPARENT", "").lower() in ("1", "true", "yes")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    window = PetWindow(transparent=transparent)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
