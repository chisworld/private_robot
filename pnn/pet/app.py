"""双窗口桌宠：人物窗、对话窗、独立 AI 气泡窗。"""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QStyle, QSystemTrayIcon

from pnn.pet.api_client import PetApiClient
from pnn.pet.asr_session import AsrSession
from pnn.pet.audio import LipSyncPlayer
from pnn.pet.bubble_window import BubbleWindow
from pnn.pet.character_window import CharacterWindow
from pnn.pet.chat_window import ChatWindow
from pnn.pet.controller import PetController
from pnn.pet.console_log import suppress_live2d_log
from pnn.pet.live2d_widget import configure_opengl_app, dispose_live2d_framework
from pnn.pet.preferences import load_preferences, save_preferences
from pnn.pet.settings_dialog import SettingsDialog
from pnn.pet.ui_constants import (
    ASR_FINAL_HOLD_MS,
    ASR_INPUT_IDLE_CLEAR_MS,
    clamp_character_scale,
)
from pnn.pet.warmup import ServiceWarmupWorker


class PetApplication:
    def __init__(self) -> None:
        self._api = PetApiClient()
        self._lip = LipSyncPlayer()
        self._ui_prefs = load_preferences()
        self._character = CharacterWindow(character_scale=self._ui_prefs.character_scale)
        self._bubble = BubbleWindow()
        self._bubble.apply_preferences(self._ui_prefs)
        self._chat = ChatWindow(self._ui_prefs)
        self._chat_streaming = False
        self._hold_speech_bubble = False
        self._controller = PetController(
            self._api,
            self._character.live2d,
            self._lip,
        )
        self._controller.set_tts_speak_mode(self._ui_prefs.tts_speak_mode)
        self._asr = AsrSession(self._api)
        self._settings: SettingsDialog | None = None
        self._warmup: ServiceWarmupWorker | None = None
        self._asr_pending_piece = ""
        self._asr_hold_timer = QTimer(self._character)
        self._asr_hold_timer.setSingleShot(True)
        self._asr_hold_timer.timeout.connect(self._flush_asr_final)
        self._asr_idle_clear_timer = QTimer(self._character)
        self._asr_idle_clear_timer.setSingleShot(True)
        self._asr_idle_clear_timer.timeout.connect(self._clear_asr_input_idle)
        self._asr_input_snapshot = ""
        self._tray: QSystemTrayIcon | None = None
        self._shutting_down = False
        self._last_bubble_text = ""
        self._last_asr_partial = ""
        self._asr_restart_timer = QTimer(self._character)
        self._asr_restart_timer.setSingleShot(True)
        self._asr_restart_timer.timeout.connect(self._ensure_asr_running)

        self._wire_signals()
        self._chat.set_mic_always_on(self._ui_prefs.asr_always_on)
        QShortcut(QKeySequence("Ctrl+M"), self._character, activated=self._toggle_asr)
        QShortcut(QKeySequence("Ctrl+M"), self._chat, activated=self._toggle_asr)

    def _wire_signals(self) -> None:
        self._character.live2d.load_succeeded.connect(self._on_live2d_ready)
        self._character.live2d.load_failed.connect(self._on_live2d_failed)
        self._character.settings_requested.connect(self._open_settings)
        self._character.chat_restore_requested.connect(self._restore_chat_and_bubble)
        self._bubble.minimized.connect(self._on_bubble_minimized)
        self._character.closed.connect(self._on_character_closed)
        self._character.scale_changed.connect(self._on_character_scale_wheel)

        self._chat.minimized_to_tray.connect(self._on_chat_minimized)
        self._chat.send_requested.connect(self._on_send)
        self._chat.mic_requested.connect(self._toggle_asr)
        self._chat.closed.connect(self._on_chat_closed)

        self._controller.bubble_changed.connect(self._on_bubble)
        self._controller.playback_started.connect(self._on_playback_started)
        self._controller.playback_finished.connect(self._on_playback_finished)
        self._controller.status_changed.connect(self._on_status)
        self._controller.loading_changed.connect(self._on_loading)

        self._asr.final_text.connect(self._on_asr_final)
        self._asr.partial_changed.connect(self._on_asr_partial)
        self._asr.status_changed.connect(self._on_asr_status)
        self._asr.error_occurred.connect(self._on_asr_error)

    def _on_live2d_ready(self) -> None:
        self._character.apply_ui_prefs(self._ui_prefs)
        self._character.live2d.start_loop()
        self._character.fit_to_model()
        self._character.set_status_hint("Live2D 已加载")

    def _on_live2d_failed(self, msg: str) -> None:
        self._character.set_status_hint(f"Live2D: {msg}")

    def _on_status(self, msg: str, is_err: bool) -> None:
        if msg.strip():
            self._character.set_status_hint(msg)

    def _on_bubble(self, text: str) -> None:
        """唯一 AI 气泡出口：仅更新独立 BubbleWindow，对话窗不显示回复。"""
        body = (text or "").strip()
        if not body:
            self._last_bubble_text = ""
            self._bubble.clear()
            return
        if body == self._last_bubble_text:
            return
        self._last_bubble_text = body
        self._character.live2d.hide_model_dialog()
        self._bubble.set_text(body, stream=False)

    def _on_playback_started(self) -> None:
        self._hold_speech_bubble = True

    def _on_playback_finished(self) -> None:
        self._hold_speech_bubble = False
        self._last_bubble_text = ""
        self._bubble.clear()
        if self._ui_prefs.asr_always_on:
            self._schedule_asr_restart(400)

    def _on_loading(self, loading: bool) -> None:
        self._chat_streaming = loading
        self._chat.set_input_enabled(not loading)
        if not loading and self._ui_prefs.asr_always_on:
            self._schedule_asr_restart(400)

    def _on_send(self, text: str) -> None:
        self._cancel_asr_hold()
        self._asr_idle_clear_timer.stop()
        self._asr_input_snapshot = ""
        self._bubble.clear()
        self._controller.send_message(text)

    def _open_settings(self) -> None:
        if self._settings is None:
            dlg = SettingsDialog(
                self._api,
                on_ui_saved=self._on_ui_prefs_saved,
                on_character_applied=self._on_character_applied,
                parent=self._character,
            )
            dlg.finished.connect(self._on_settings_closed)
            self._settings = dlg
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def _on_settings_closed(self) -> None:
        self._settings = None

    def _on_character_applied(self) -> None:
        from pnn.core.paths import live2d_model_dir

        model_json = live2d_model_dir() / "我也要死吗.model3.json"
        self._character.live2d.reload_model(model_json)
        self._character.fit_to_model()
        self._character.set_status_hint("已切换角色包")

    def _on_ui_prefs_saved(self, prefs) -> None:
        self._ui_prefs = prefs
        self._controller.set_tts_speak_mode(prefs.tts_speak_mode)
        self._chat.apply_preferences(prefs)
        self._bubble.apply_preferences(prefs)
        self._character.apply_ui_prefs(prefs)
        self._chat.set_mic_always_on(prefs.asr_always_on)
        if prefs.asr_always_on and not self._asr.is_active():
            self._schedule_asr_restart(300)

    def _toggle_asr(self) -> None:
        """麦克风按钮：开关「常开 + 说完自动发送」。"""
        if self._ui_prefs.asr_always_on:
            self._ui_prefs.asr_always_on = False
            save_preferences(self._ui_prefs)
            self._cancel_asr_hold()
            self._asr.stop()
            self._chat.set_mic_always_on(False)
            self._chat.set_asr_active(False)
            return
        self._ui_prefs.asr_always_on = True
        save_preferences(self._ui_prefs)
        self._chat.set_mic_always_on(True)
        self._asr.start()

    def _schedule_asr_restart(self, delay_ms: int) -> None:
        if not self._ui_prefs.asr_always_on:
            return
        self._asr_restart_timer.start(max(50, delay_ms))

    def _ensure_asr_running(self) -> None:
        if not self._ui_prefs.asr_always_on:
            return
        if not self._asr.is_active():
            self._asr.start()

    def _on_asr_status(self, status: str) -> None:
        active = status in ("loading", "listening", "speech")
        self._chat.set_asr_active(active)

    def _cancel_asr_hold(self) -> None:
        if self._asr_hold_timer.isActive():
            self._asr_hold_timer.stop()
        self._asr_pending_piece = ""

    def _clear_asr_input_idle(self) -> None:
        """识别结束或停顿后清空输入框（不发送）。"""
        if self._asr_hold_timer.isActive():
            return
        if self._chat.input_text().strip() != self._asr_input_snapshot.strip():
            return
        self._chat.set_input_text("")
        self._last_asr_partial = ""
        self._asr_pending_piece = ""

    def _schedule_asr_input_clear(self, text: str) -> None:
        self._asr_input_snapshot = text.strip()
        self._asr_idle_clear_timer.start(ASR_INPUT_IDLE_CLEAR_MS)

    def _on_character_scale_wheel(self, scale: float) -> None:
        scale = clamp_character_scale(scale)
        self._ui_prefs.character_scale = scale
        self._character.set_character_scale(scale)
        save_preferences(self._ui_prefs)

    def _on_asr_partial(self, text: str) -> None:
        piece = text.strip()
        if not piece or piece == self._last_asr_partial:
            return
        self._last_asr_partial = piece
        self._cancel_asr_hold()
        self._asr_idle_clear_timer.stop()
        self._chat.clear_asr_preview()
        self._chat.set_input_text(piece)
        self._schedule_asr_input_clear(piece)

    def _on_asr_error(self, err: str) -> None:
        self._chat.set_asr_active(False)
        self._chat.set_input_text(f"ASR: {err}")
        self._chat.clear_asr_preview()
        if self._ui_prefs.asr_always_on:
            self._schedule_asr_restart(2000)

    def _on_asr_final(self, text: str) -> None:
        piece = text.strip()
        if not piece:
            return
        self._last_asr_partial = piece
        self._asr_pending_piece = piece
        self._asr_idle_clear_timer.stop()
        self._chat.clear_asr_preview()
        self._chat.set_input_text(piece)
        self._asr_input_snapshot = piece
        if self._ui_prefs.asr_always_on:
            self._asr_hold_timer.start(ASR_FINAL_HOLD_MS)
        else:
            self._schedule_asr_input_clear(piece)

    def _flush_asr_final(self) -> None:
        piece = self._chat.input_text().strip() or self._asr_pending_piece.strip()
        self._asr_pending_piece = ""
        self._asr_input_snapshot = ""
        self._asr_idle_clear_timer.stop()
        self._chat.clear_asr_preview()
        self._chat.set_input_text("")
        self._last_asr_partial = ""
        if not piece:
            return
        if self._controller.is_busy():
            self._controller.stop_audio(emit_finished=True)
            self._hold_speech_bubble = False
            self._bubble.clear()
        self._controller.send_message(piece, interrupt=True)

    def _on_character_closed(self) -> None:
        """关闭人物窗（✕）即退出整个桌宠，而非只关一个窗口。"""
        self._shutdown_application()

    def _on_chat_closed(self) -> None:
        if not self._character.isVisible():
            self._shutdown_application()

    def _shutdown_application(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        setattr(self._character, "_pet_exiting", True)
        print("[pet] 正在退出桌宠…", flush=True)

        self._cancel_asr_hold()
        self._asr_idle_clear_timer.stop()
        self._asr_restart_timer.stop()
        self._controller.interrupt_current()
        self._asr.stop()
        self._controller.stop_audio()

        if self._warmup is not None and self._warmup.isRunning():
            self._warmup.wait(400)

        if self._settings is not None:
            self._settings.close()
            self._settings = None

        if self._tray is not None:
            self._tray.hide()
            self._tray.setVisible(False)
            self._tray = None

        try:
            from pnn.memory.service import memory_service

            memory_service.on_shutdown()
        except Exception:
            pass

        # QuitOnLastWindowClosed(False)：只关人物窗不会结束进程，须显式关掉全部窗口并 exit
        self._bubble.close()
        self._chat.close()
        self._character.close()

        app = QApplication.instance()
        if app is not None:
            app.exit(0)

    def _start_warmup(self) -> None:
        if self._warmup is not None and self._warmup.isRunning():
            return
        self._warmup = ServiceWarmupWorker(self._api, self._character)
        self._warmup.status_changed.connect(self._on_warmup_status)
        self._warmup.finished.connect(self._warmup.deleteLater)
        self._warmup.start()

    def _on_warmup_status(self, msg: str, is_err: bool) -> None:
        if msg.strip():
            self._character.set_status_hint(msg)

    def _restore_chat_and_bubble(self) -> None:
        if self._chat.isMinimized() or not self._chat.isVisible():
            self._chat.showNormal()
        self._chat.raise_()
        self._chat.activateWindow()
        if self._bubble.has_content():
            self._show_bubble()

    def _on_bubble_minimized(self) -> None:
        self._character.set_status_hint("气泡已最小化 · 点人物上 💬 可再次显示")

    def _restore_chat(self) -> None:
        self._restore_chat_and_bubble()

    def _show_bubble(self) -> None:
        if not self._bubble.has_content():
            return
        if self._bubble.isMinimized() or not self._bubble.isVisible():
            self._bubble.showNormal()
        self._bubble.show()
        self._bubble.raise_()

    def _show_character(self) -> None:
        if self._character.isMinimized() or not self._character.isVisible():
            self._character.showNormal()
        self._character.raise_()
        self._character.activateWindow()

    def _place_windows(self) -> None:
        self._character.fit_to_model()
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        cx = geo.x() + (geo.width() - self._character.width()) // 2 - 80
        cy = geo.y() + (geo.height() - self._character.height()) // 2
        self._character.move(max(geo.x(), cx), max(geo.y(), cy))
        bx = max(geo.x(), cx + self._character.width() + 16)
        self._chat.move(bx, max(geo.y(), cy))
        self._bubble.move(bx, max(geo.y(), cy + self._chat.height() + 8))

    def _present_windows(self) -> None:
        for win in (self._character, self._chat):
            if win.isMinimized():
                win.showNormal()
            win.show()
            win.raise_()
        self._chat.activateWindow()
        self._character.set_status_hint("桌宠已启动 · 找不见请看任务栏或托盘")

    def start(self) -> None:
        self._present_windows()
        self._place_windows()
        self._bubble.hide()
        self._setup_tray()
        QTimer.singleShot(0, self._deferred_boot)
        print(
            "[pet] 窗口已显示：人物窗 + 对话窗 + 气泡窗（有 AI 回复时自动出现）",
            flush=True,
        )

    def _deferred_boot(self) -> None:
        if not self._controller.prepare():
            self._character.set_status_hint("API 未启动 (8765) · 可先运行 启动桌宠.bat")
        self._start_warmup()
        if self._ui_prefs.asr_always_on:
            self._schedule_asr_restart(1200)

    def _on_chat_minimized(self) -> None:
        self._character.set_status_hint("对话窗已最小化 · 点人物上 💬 或任务栏恢复")

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("[pet] 系统托盘不可用，请从任务栏切换人物窗/对话窗", flush=True)
            return
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self._tray = QSystemTrayIcon(icon, self._character)
        self._tray.setToolTip("14酱桌宠")
        menu = QMenu()
        act_char = QAction("显示人物窗", self._character)
        act_char.triggered.connect(self._show_character)
        menu.addAction(act_char)
        act_chat = QAction("显示对话窗", self._character)
        act_chat.triggered.connect(self._restore_chat)
        menu.addAction(act_chat)
        act_bubble = QAction("显示 AI 气泡窗", self._character)
        act_bubble.triggered.connect(self._show_bubble)
        menu.addAction(act_bubble)
        menu.addSeparator()
        act_quit = QAction("退出", self._character)
        act_quit.triggered.connect(self._shutdown_application)
        menu.addAction(act_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._restore_chat_and_bubble()
            self._show_character()


def _install_qt_message_filter() -> None:
    """屏蔽 Qt 对部分控件 setStyleSheet 的无害警告（避免终端刷屏）。"""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return

    _skip = (
        "Could not parse stylesheet",
        "Unknown property",
    )

    def _handler(mode, context, message) -> None:
        if any(s in message for s in _skip):
            return
        if mode == QtMsgType.QtWarningMsg:
            print(f"[qt] {message}", flush=True)
        elif mode == QtMsgType.QtCriticalMsg:
            print(f"[qt-critical] {message}", flush=True)

    qInstallMessageHandler(_handler)


def main() -> None:
    from pnn.core.audio_cache import prune_audio_cache
    from pnn.core.env import load_env
    from pnn.core.logging import setup_logging

    load_env()
    setup_logging()
    prune_audio_cache()
    suppress_live2d_log()
    _install_qt_message_filter()
    print("[pet] 正在启动界面…", flush=True)
    try:
        configure_opengl_app()
    except Exception as exc:
        print(f"[pet] OpenGL 配置失败: {exc}", flush=True)
        raise
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setQuitOnLastWindowClosed(False)
    try:
        pet = PetApplication()
        pet.start()
    except Exception as exc:
        QMessageBox.critical(
            None,
            "桌宠启动失败",
            f"{exc}\n\n请确认 conda 环境 AI 已安装 PySide6、live2d-py、PyOpenGL。",
        )
        raise
    print("[pet] 进入事件循环（关闭人物窗 ✕ 或托盘「退出」结束）", flush=True)
    code = app.exec()
    dispose_live2d_framework()
    raise SystemExit(code if code else 0)
