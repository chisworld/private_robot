"""双窗口桌宠：人物窗、对话窗、独立 AI 气泡窗。"""

from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QTimer, Qt
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
from pnn.pet.preferences import load_preferences, merge_preferences, patch_preferences, save_preferences
from pnn.pet.ui_constants import (
    ASR_FINAL_HOLD_MS,
    ASR_INPUT_IDLE_CLEAR_MS,
    clamp_character_scale,
)
from pnn.pet.warmup import ServiceWarmupWorker

# Live2D 就绪后先问候语音，其余服务稍晚再拉
_BACKGROUND_BOOT_DELAY_MS = 1500
_CHAT_FALLBACK_DELAY_MS = 8000


class PetApplication:
    def __init__(self) -> None:
        self._api = PetApiClient()
        self._lip = LipSyncPlayer()
        self._ui_prefs = load_preferences()
        self._character = CharacterWindow(character_scale=self._ui_prefs.character_scale)
        self._bubble = BubbleWindow()
        self._bubble.restore_geometry(self._ui_prefs)
        self._bubble.apply_preferences(self._ui_prefs)
        self._bubble.geometry_changed.connect(self._persist_bubble_geometry)
        self._chat = ChatWindow(self._ui_prefs)
        self._chat.restore_geometry(self._ui_prefs)
        self._chat.geometry_changed.connect(self._persist_chat_geometry)
        self._chat_streaming = False
        self._hold_speech_bubble = False
        self._bubble_clear_timer = QTimer()
        self._bubble_clear_timer.setSingleShot(True)
        self._bubble_clear_timer.timeout.connect(self._clear_bubble_now)
        self._controller = PetController(
            self._api,
            self._character.live2d,
            self._lip,
        )
        self._controller.set_voice_output_enabled(self._ui_prefs.voice_output_enabled)
        self._asr = AsrSession(self._api)
        self._settings = None
        self._warmup: ServiceWarmupWorker | None = None
        self._greeting_retry_left = 12
        self._secondary_windows_shown = False
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
        self._pending_screenshot_b64 = ""
        self._pending_screenshot_mime = "image/png"
        self._pending_screenshot_analysis = ""
        self._asr_restart_timer = QTimer(self._character)
        self._asr_restart_timer.setSingleShot(True)
        self._asr_restart_timer.timeout.connect(self._ensure_asr_running)
        self._prefs_save_timer = QTimer(self._character)
        self._prefs_save_timer.setSingleShot(True)
        self._prefs_save_timer.setInterval(500)
        self._prefs_save_timer.timeout.connect(self._flush_deferred_prefs_save)
        self._api_watchdog = QTimer(self._character)
        self._api_watchdog.setInterval(30_000)
        self._api_watchdog.timeout.connect(self._api_watchdog_tick)
        self._api_watchdog_fail_streak = 0

        self._wire_signals()
        self._chat.set_mic_always_on(self._ui_prefs.asr_always_on)
        QShortcut(QKeySequence("Ctrl+M"), self._character, activated=self._toggle_asr)
        QShortcut(QKeySequence("Ctrl+M"), self._chat, activated=self._toggle_asr)
        paste_sc = QShortcut(QKeySequence.StandardKey.Paste, self._character)
        paste_sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        paste_sc.activated.connect(self._paste_screenshot_on_character)

    def _wire_signals(self) -> None:
        self._character.live2d.load_succeeded.connect(self._on_live2d_ready)
        self._character.live2d.load_failed.connect(self._on_live2d_failed)
        self._character.settings_requested.connect(self._open_settings)
        self._character.chat_restore_requested.connect(self._restore_chat_and_bubble)
        self._bubble.minimized.connect(self._on_bubble_minimized)
        self._character.closed.connect(self._on_character_closed)
        self._character.scale_changed.connect(self._on_character_scale_wheel)
        self._character.size_changed_by_user.connect(self._on_character_size_changed)
        self._character.screenshot_attached.connect(self._on_screenshot_attached)

        self._chat.minimized_to_tray.connect(self._on_chat_minimized)
        self._chat.send_requested.connect(self._on_send)
        self._chat.mic_requested.connect(self._toggle_asr)
        self._chat.closed.connect(self._on_chat_closed)

        self._controller.bubble_changed.connect(self._on_bubble)
        self._controller.playback_started.connect(self._on_playback_started)
        self._controller.playback_finished.connect(self._on_playback_finished)
        self._controller.status_changed.connect(self._on_status)
        self._controller.loading_changed.connect(self._on_loading)
        self._controller.screenshot_analysis_ready.connect(self._on_screenshot_analysis_ready)

        self._asr.final_text.connect(self._on_asr_final)
        self._asr.partial_changed.connect(self._on_asr_partial)
        self._asr.status_changed.connect(self._on_asr_status)
        self._asr.error_occurred.connect(self._on_asr_error)

    def _on_live2d_ready(self) -> None:
        self._sync_ui_from_disk()
        self._character.live2d.start_loop()
        self._character.fit_to_model()
        self._present_secondary_windows()
        self._place_windows()
        self._character.set_status_hint("Live2D 已加载")
        QTimer.singleShot(0, self._start_voice_boot)
        QTimer.singleShot(_BACKGROUND_BOOT_DELAY_MS, self._start_background_services)

    def _sync_ui_from_disk(self) -> None:
        """从 pet_ui.json 重新加载并应用到对话窗/气泡窗（启动与 Live2D 就绪后调用）。"""
        char_id = self._get_active_character_id()
        self._ui_prefs = load_preferences().get_for_character(char_id)
        self._controller.set_voice_output_enabled(self._ui_prefs.voice_output_enabled)
        self._controller.set_stream_bubble_output(self._ui_prefs.stream_bubble_output)
        self._chat.apply_preferences(self._ui_prefs)
        self._bubble.apply_preferences(self._ui_prefs)
        self._character.apply_ui_prefs(self._ui_prefs)
        self._character.live2d.set_idle_amplitude(self._ui_prefs.idle_motion_amplitude)
        self._chat.set_mic_always_on(self._ui_prefs.asr_always_on)
        self._chat.restore_geometry(self._ui_prefs)
        self._bubble.restore_geometry(self._ui_prefs)

    def _on_live2d_failed(self, msg: str) -> None:
        self._character.set_status_hint(f"Live2D: {msg}")

    def _on_status(self, msg: str, is_err: bool) -> None:
        if msg.strip():
            self._character.set_status_hint(msg)

    def _on_bubble(self, text: str, is_stream: bool = False) -> None:
        """唯一 AI 气泡出口：仅更新独立 BubbleWindow，对话窗不显示回复。"""
        body = (text or "").strip()
        if not body:
            self._last_bubble_text = ""
            self._bubble.clear()
            return
        if not is_stream and body == self._last_bubble_text:
            return
        self._bubble_clear_timer.stop()
        self._last_bubble_text = body
        self._character.live2d.hide_model_dialog()
        self._bubble.set_text(body, stream=is_stream)
        if self._bubble.isMinimized():
            self._bubble.showNormal()
        self._bubble.show()
        self._bubble.raise_()

    def _on_playback_started(self) -> None:
        self._hold_speech_bubble = True
        self._bubble_clear_timer.stop()

    def _clear_bubble_now(self) -> None:
        if (
            self._controller.is_playing_audio()
            or self._controller.has_pending_voice_playback()
        ):
            return
        self._last_bubble_text = ""
        self._bubble.clear()

    def _on_playback_finished(self) -> None:
        self._hold_speech_bubble = False
        self._bubble_clear_timer.stop()
        # 分句播放中间会有极短间隙，此时仍可能有后续句
        if self._controller.has_pending_voice_playback():
            return
        if self._pending_screenshot_b64:
            if self._bubble.has_content():
                self._bubble_clear_timer.start(
                    max(self._bubble.suggested_read_ms(), 2800)
                )
            else:
                self._clear_bubble_now()
            if self._ui_prefs.asr_always_on:
                self._schedule_asr_restart(400)
            return
        if self._bubble.has_content():
            ms = max(self._bubble.suggested_read_ms(), 4000)
            self._bubble_clear_timer.start(ms)
        else:
            self._clear_bubble_now()
        if self._ui_prefs.asr_always_on:
            self._schedule_asr_restart(400)

    def _on_loading(self, loading: bool) -> None:
        self._chat_streaming = loading
        self._chat.set_input_enabled(not loading)
        if not loading and self._ui_prefs.asr_always_on:
            self._schedule_asr_restart(400)

    def _on_screenshot_analysis_ready(self, analysis: str) -> None:
        self._pending_screenshot_analysis = (analysis or "").strip()

    def _on_screenshot_attached(self, image_base64: str, image_mime: str) -> None:
        self._pending_screenshot_b64 = (image_base64 or "").strip()
        self._pending_screenshot_mime = image_mime or "image/png"
        self._pending_screenshot_analysis = ""
        self._last_bubble_text = ""
        self._bubble.clear()
        self._controller.announce_screenshot_recognized(
            self._pending_screenshot_b64,
            self._pending_screenshot_mime,
        )

    def _paste_screenshot_on_character(self) -> None:
        """鼠标在人物上时 Ctrl+V：从剪贴板贴截图。"""
        if not self._character.can_accept_screenshot_input():
            return
        self._character.paste_screenshot_from_clipboard()

    def _on_send(self, text: str) -> None:
        self._cancel_asr_hold()
        self._asr_idle_clear_timer.stop()
        self._asr_input_snapshot = ""
        self._bubble_clear_timer.stop()
        self._bubble.clear()
        msg = (text or "").strip()
        img = self._pending_screenshot_b64
        if not msg and not img:
            return
        self._controller.send_message(
            msg,
            interrupt=self._controller.is_busy(),
            image_base64=img,
            image_mime=self._pending_screenshot_mime,
            image_analysis=self._pending_screenshot_analysis,
        )
        self._pending_screenshot_b64 = ""
        self._pending_screenshot_mime = "image/png"
        self._pending_screenshot_analysis = ""

    def _open_settings(self) -> None:
        if self._settings is None:
            from pnn.pet.settings_dialog import SettingsDialog

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
        from pnn.core.paths import PROJECT_ROOT, _find_model3_json, invalidate_live2d_path_cache, live2d_model_json

        invalidate_live2d_path_cache()
        self._sync_ui_from_disk()

        variant_dir = self._ui_prefs.live2d_variant_dir
        if variant_dir:
            variant_path = PROJECT_ROOT / variant_dir
            model_json = _find_model3_json(variant_path)
        else:
            model_json = None
        if model_json is None:
            model_json = live2d_model_json()
        self._character.live2d.reload_model(model_json)
        self._character.fit_to_model()
        self._character.set_status_hint("已切换角色包")

    def _get_active_character_id(self) -> str:
        try:
            cfg = self._api.get_chat_config()
            return str(cfg.get("active_character", ""))
        except Exception:
            return ""

    def _persist_bubble_geometry(self) -> None:
        x, y, w, h = self._bubble.capture_geometry()
        merged = patch_preferences(
            bubble_window_x=x,
            bubble_window_y=y,
            bubble_window_w=w,
            bubble_window_h=h,
        )
        self._ui_prefs = merged.get_for_character(self._get_active_character_id())

    def _persist_chat_geometry(self) -> None:
        x, y, w, h = self._chat.capture_geometry()
        merged = patch_preferences(
            chat_window_x=x,
            chat_window_y=y,
            chat_window_w=w,
            chat_window_h=h,
        )
        self._ui_prefs = merged.get_for_character(self._get_active_character_id())

    def _on_ui_prefs_saved(self, prefs) -> None:
        self._ui_prefs = prefs
        self._controller.set_voice_output_enabled(prefs.voice_output_enabled)
        self._controller.set_stream_bubble_output(prefs.stream_bubble_output)
        self._chat.apply_preferences(prefs)
        self._bubble.apply_preferences(prefs)
        self._character.apply_ui_prefs(prefs)
        self._character.live2d.set_idle_amplitude(prefs.idle_motion_amplitude)
        self._chat.set_mic_always_on(prefs.asr_always_on)
        if prefs.asr_always_on and not self._asr.is_active():
            self._schedule_asr_restart(300)
        # 保存后立即写盘，避免仅改界面项但未等几何变更时丢失
        merged = merge_preferences(load_preferences(), prefs)
        save_preferences(merged)
        self._ui_prefs = merged.get_for_character(self._get_active_character_id())

    def _toggle_asr(self) -> None:
        """麦克风按钮：开关「常开 + 说完自动发送」。"""
        char_id = self._get_active_character_id()
        if self._ui_prefs.asr_always_on:
            patch_preferences(asr_always_on=False)
            self._ui_prefs = load_preferences().get_for_character(char_id)
            self._cancel_asr_hold()
            self._asr.stop()
            self._chat.set_mic_always_on(False)
            self._chat.set_asr_active(False)
            return
        patch_preferences(asr_always_on=True)
        self._ui_prefs = load_preferences().get_for_character(char_id)
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

    def _schedule_prefs_save(self) -> None:
        self._prefs_save_timer.start()

    def _flush_deferred_prefs_save(self) -> None:
        char_id = self._get_active_character_id()
        merged = merge_preferences(load_preferences(), self._ui_prefs)
        save_preferences(merged)
        self._ui_prefs = merged.get_for_character(char_id)

    def _on_character_scale_wheel(self, scale: float) -> None:
        scale = clamp_character_scale(scale)
        self._ui_prefs.character_scale = scale
        self._character.set_character_scale(scale)
        char_id = self._get_active_character_id()
        self._ui_prefs.set_for_character(
            char_id,
            scale=scale,
            fill=self._ui_prefs.fill_percent,
            crop=self._ui_prefs.crop_shrink_percent,
            variant_dir=self._ui_prefs.live2d_variant_dir,
            width_px=self._ui_prefs.character_width_px,
            height_px=self._ui_prefs.character_height_px,
        )
        self._schedule_prefs_save()

    def _on_character_size_changed(self, width: int, height: int) -> None:
        self._ui_prefs.character_width_px = width
        self._ui_prefs.character_height_px = height
        char_id = self._get_active_character_id()
        self._ui_prefs.set_for_character(
            char_id,
            scale=self._ui_prefs.character_scale,
            fill=self._ui_prefs.fill_percent,
            crop=self._ui_prefs.crop_shrink_percent,
            variant_dir=self._ui_prefs.live2d_variant_dir,
            width_px=width,
            height_px=height,
        )
        self._schedule_prefs_save()

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
        if not piece and not self._pending_screenshot_b64:
            return
        if self._controller.is_busy():
            self._controller.interrupt_current()
            self._hold_speech_bubble = False
        img = self._pending_screenshot_b64
        mime = self._pending_screenshot_mime
        analysis = self._pending_screenshot_analysis
        self._pending_screenshot_b64 = ""
        self._pending_screenshot_mime = "image/png"
        self._pending_screenshot_analysis = ""
        self._controller.send_message(
            piece,
            interrupt=True,
            image_base64=img,
            image_mime=mime,
            image_analysis=analysis,
        )

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
        self._api_watchdog.stop()
        self._controller.interrupt_current()
        self._asr.stop()
        self._controller.stop_audio()

        self._stop_warmup(wait_ms=400)

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

        self._persist_bubble_geometry()
        self._persist_chat_geometry()

        # QuitOnLastWindowClosed(False)：只关人物窗不会结束进程，须显式关掉全部窗口并 exit
        self._bubble.close()
        self._chat.close()
        self._character.close()

        app = QApplication.instance()
        if app is not None:
            app.exit(0)

    def _clear_warmup_ref(self, worker: ServiceWarmupWorker) -> None:
        if self._warmup is worker:
            self._warmup = None

    def _stop_warmup(self, *, wait_ms: int = 0) -> None:
        worker = self._warmup
        self._warmup = None
        if worker is None:
            return
        try:
            if worker.isRunning():
                worker.wait(max(0, wait_ms))
        except RuntimeError:
            pass

    def _start_warmup(self) -> None:
        worker = self._warmup
        if worker is not None:
            try:
                if worker.isRunning():
                    return
            except RuntimeError:
                self._warmup = None
        worker = ServiceWarmupWorker(self._api, self._character)
        self._warmup = worker
        worker.status_changed.connect(self._on_warmup_status)
        worker.finished_ok.connect(self._on_warmup_finished)
        worker.finished.connect(lambda: self._clear_warmup_ref(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_warmup_finished(self, ok: bool) -> None:
        if self._shutting_down:
            return
        if not self._controller.startup_greeting_played():
            QTimer.singleShot(600, self._try_time_greeting)
        if ok or self._api.tts_server_online():
            return
        self._greeting_retry_left = 12
        QTimer.singleShot(20_000, self._retry_time_greeting)

    def _retry_time_greeting(self) -> None:
        if self._shutting_down or not self._ui_prefs.voice_output_enabled:
            return
        if self._greeting_retry_left <= 0:
            return
        self._greeting_retry_left -= 1
        if self._api.wait_tts_ready(timeout=3.0, poll=0.5) or self._api.tts_server_online():
            self._try_time_greeting()
        QTimer.singleShot(20_000, self._retry_time_greeting)

    def _try_time_greeting(self) -> None:
        if self._shutting_down or not self._ui_prefs.voice_output_enabled:
            return
        self._controller.try_time_greeting()

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
        if self._ui_prefs.chat_window_x < 0 or self._ui_prefs.chat_window_y < 0:
            self._chat.move(bx, max(geo.y(), cy))
        if self._ui_prefs.bubble_window_x < 0 or self._ui_prefs.bubble_window_y < 0:
            self._bubble.move(bx, max(geo.y(), cy + self._chat.height() + 8))

    def _present_character_only(self) -> None:
        if self._character.isMinimized():
            self._character.showNormal()
        self._character.show()
        self._character.raise_()
        self._character.set_status_hint("正在加载 Live2D 模型…")

    def _present_secondary_windows(self) -> None:
        if self._secondary_windows_shown:
            return
        self._secondary_windows_shown = True
        if self._chat.isMinimized():
            self._chat.showNormal()
        self._chat.show()
        self._chat.raise_()
        self._chat.activateWindow()
        self._character.set_status_hint("桌宠已启动 · 找不见请看任务栏或托盘")

    def _present_secondary_windows_fallback(self) -> None:
        if self._secondary_windows_shown:
            return
        self._present_secondary_windows()
        self._place_windows()

    def _present_windows(self) -> None:
        self._present_character_only()
        self._present_secondary_windows()

    def _start_voice_boot(self) -> None:
        """Live2D 就绪后：播放时段问候（API/TTS 已在人物窗出现时后台预热）。"""
        if self._shutting_down:
            return
        self._try_time_greeting()

    def _start_background_services(self) -> None:
        """问候与模型就绪后：角色包、ASR、缓存清理等非首屏任务。"""
        if self._shutting_down:
            return
        from pnn.pet.boot_services import prune_audio_cache_async

        prune_audio_cache_async()
        if not self._controller.prepare():
            self._character.set_status_hint("API 未启动 (8765) · 后台继续连接…")
        else:
            char_id = self._get_active_character_id()
            if char_id:

                def _apply_pack() -> None:
                    import time

                    last_exc: Exception | None = None
                    for attempt in range(2):
                        try:
                            if not self._api.apply_character_pack_if_needed(
                                char_id, timeout=45.0
                            ):
                                print(f"[pet] 角色包已由 API 应用: {char_id}", flush=True)
                                return
                            print(f"[pet] 已应用角色包: {char_id}", flush=True)
                            return
                        except Exception as exc:
                            last_exc = exc
                            msg = str(exc)
                            if attempt == 0 and (
                                "timed out" in msg.lower() or "timeout" in msg.lower()
                            ):
                                time.sleep(2.0)
                                continue
                            break
                    if last_exc is not None:
                        msg = str(last_exc)
                        if "timed out" in msg.lower() or "timeout" in msg.lower():
                            print(
                                f"[pet] 应用角色包超时（API 可能正忙 TTS 预热）；"
                                f"启动时 API 通常已应用 {char_id}，可忽略",
                                flush=True,
                            )
                        else:
                            print(f"[pet] 应用角色包失败: {last_exc}", flush=True)

                threading.Thread(
                    target=_apply_pack,
                    name="pet-apply-pack",
                    daemon=True,
                ).start()
        if self._ui_prefs.asr_always_on:
            self._schedule_asr_restart(1200)
        if not self._api_watchdog.isActive():
            self._api_watchdog.start()

    def _api_watchdog_tick(self) -> None:
        if self._shutting_down:
            return

        def _check() -> None:
            from pnn.pet.api_guard import is_api_responsive, recover_api_if_stuck

            if is_api_responsive(timeout=3.0):
                self._api_watchdog_fail_streak = 0
                return
            self._api_watchdog_fail_streak += 1
            if self._api_watchdog_fail_streak < 2:
                return
            self._api_watchdog_fail_streak = 0
            if recover_api_if_stuck(reason="后台看门狗"):
                self._api.reset_http()

        threading.Thread(target=_check, name="pet-api-watchdog", daemon=True).start()

    def start(self) -> None:
        self._present_character_only()
        self._bubble.hide()
        self._setup_tray()
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            cx = geo.x() + (geo.width() - self._character.width()) // 2 - 80
            cy = geo.y() + (geo.height() - self._character.height()) // 2
            self._character.move(max(geo.x(), cx), max(geo.y(), cy))
        QTimer.singleShot(_CHAT_FALLBACK_DELAY_MS, self._present_secondary_windows_fallback)
        from pnn.pet.boot_services import ensure_api_and_kick_tts_async

        ensure_api_and_kick_tts_async()
        self._start_warmup()
        print(
            "[pet] 人物窗已显示，后台预热 API/TTS；Live2D 就绪后播放问候语音",
            flush=True,
        )

    def _deferred_boot(self) -> None:
        """兼容旧调用；启动流程已改为分阶段 boot。"""
        self._start_background_services()

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
    from pnn.core.env import load_env
    from pnn.core.logging import setup_logging

    load_env()
    setup_logging()
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
    print("[pet] Entering event loop (close character window or tray Exit to quit)", flush=True)
    code = app.exec()
    dispose_live2d_framework()
    raise SystemExit(code if code else 0)
