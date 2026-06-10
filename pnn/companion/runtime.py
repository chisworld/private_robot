"""代码/写作陪伴运行时（桌宠侧 QObject）。"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from pnn.companion.build_watcher import BuildLogWatcher
from pnn.companion.config_store import CompanionConfig, load_companion_config
from pnn.companion.writing_monitor import WritingIdleTracker

logger = logging.getLogger(__name__)

_runtime: "CompanionRuntime | None" = None


def set_companion_runtime(rt: "CompanionRuntime | None") -> None:
    global _runtime
    _runtime = rt


def get_companion_runtime() -> "CompanionRuntime | None":
    return _runtime


class CompanionRuntime(QObject):
    """监听构建日志与写作 idle，向桌宠 UI 发信号。"""

    compile_failed = Signal()
    compile_success = Signal()
    writing_nudge = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = load_companion_config()
        self._build = BuildLogWatcher(self._config.build_log_paths)
        self._writing = WritingIdleTracker(idle_minutes=self._config.writing_idle_minutes)
        self._build_timer = QTimer(self)
        self._build_timer.timeout.connect(self._on_build_tick)
        self._write_timer = QTimer(self)
        self._write_timer.timeout.connect(self._on_writing_tick)
        self._last_compile_event_at: datetime | None = None

    def reload_config(self) -> None:
        self._config = load_companion_config()
        self._build.set_paths(self._config.build_log_paths)
        self._writing.set_idle_minutes(self._config.writing_idle_minutes)
        self._reschedule()

    def touch_user_activity(self) -> None:
        self._writing.touch_user_activity()

    def start(self) -> None:
        self._reschedule()

    def stop(self) -> None:
        self._build_timer.stop()
        self._write_timer.stop()

    def _reschedule(self) -> None:
        cfg = self._config
        self._build_timer.stop()
        self._write_timer.stop()
        if not cfg.enabled:
            return
        if cfg.build_watch_enabled and cfg.build_log_paths:
            self._build_timer.start(max(5000, cfg.build_poll_seconds * 1000))
        if cfg.writing_nudge_enabled:
            self._write_timer.start(max(30000, cfg.writing_poll_seconds * 1000))

    def _compile_cooldown_ok(self) -> bool:
        cfg = self._config
        if self._last_compile_event_at is None:
            return True
        return (datetime.now() - self._last_compile_event_at).total_seconds() >= cfg.compile_cooldown_seconds

    def _on_build_tick(self) -> None:
        if not self._config.enabled or not self._config.build_watch_enabled:
            return
        if not self._compile_cooldown_ok():
            return
        try:
            event = self._build.poll()
        except Exception:
            logger.exception("构建日志检测失败")
            return
        if event == "failed":
            self._last_compile_event_at = datetime.now()
            logger.info("[companion] 检测到编译/构建失败")
            self.compile_failed.emit()
        elif event == "success":
            self._last_compile_event_at = datetime.now()
            logger.info("[companion] 检测到编译/构建成功")
            self.compile_success.emit()

    def _on_writing_tick(self) -> None:
        if not self._config.enabled or not self._config.writing_nudge_enabled:
            return
        try:
            if self._writing.should_nudge(cooldown_seconds=max(300, self._config.writing_idle_minutes * 60)):
                logger.info("[companion] 写作/编码 idle 捧哏")
                self.writing_nudge.emit()
        except Exception:
            logger.exception("写作 idle 检测失败")

    def get_config(self) -> dict:
        cfg = self._config
        return {
            "enabled": cfg.enabled,
            "build_watch_enabled": cfg.build_watch_enabled,
            "writing_nudge_enabled": cfg.writing_nudge_enabled,
            "build_log_paths": list(cfg.build_log_paths),
            "build_poll_seconds": cfg.build_poll_seconds,
            "writing_idle_minutes": cfg.writing_idle_minutes,
            "writing_poll_seconds": cfg.writing_poll_seconds,
            "compile_cooldown_seconds": cfg.compile_cooldown_seconds,
        }

    def update_config(self, **kwargs) -> CompanionConfig:
        from pnn.companion.config_store import save_companion_config

        cfg = load_companion_config()
        for key, val in kwargs.items():
            if hasattr(cfg, key) and val is not None:
                setattr(cfg, key, val)
        save_companion_config(cfg)
        self._config = cfg
        self.reload_config()
        return cfg

    def notify_ide_event(self, kind: str) -> None:
        """HTTP/扩展钩子：compile_failed | compile_success。"""
        k = (kind or "").strip().lower()
        if k in ("failed", "fail", "compile_failed", "error"):
            if self._compile_cooldown_ok():
                self._last_compile_event_at = datetime.now()
                self.compile_failed.emit()
        elif k in ("success", "ok", "compile_success", "passed"):
            if self._compile_cooldown_ok():
                self._last_compile_event_at = datetime.now()
                self.compile_success.emit()
