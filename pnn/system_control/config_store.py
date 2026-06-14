"""本机系统操控配置 data/config/system_control.json"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pnn.core.config_cache import MtimeJsonConfigCache
from pnn.core.paths import PROJECT_ROOT

SYSTEM_CONTROL_CONFIG_PATH = PROJECT_ROOT / "data" / "config" / "system_control.json"

LOCAL_SERVER_ID = "local"
SET_VOLUME_TOOL = "set_volume"
SET_BRIGHTNESS_TOOL = "set_brightness"
MEDIA_CONTROL_TOOL = "media_control"
EMPTY_RECYCLE_BIN_TOOL = "empty_recycle_bin"
SCHEDULE_SHUTDOWN_TOOL = "schedule_shutdown"
CANCEL_SHUTDOWN_TOOL = "cancel_shutdown"

MEDIA_ACTION_PLAY_PAUSE = "play_pause"
MEDIA_ACTION_NEXT = "next"
MEDIA_ACTION_PREVIOUS = "previous"


@dataclass
class SystemControlConfig:
    enabled: bool = True
    use_in_chat: bool = True
    allow_shutdown: bool = True
    allow_recycle_bin: bool = True
    allow_volume: bool = True
    allow_brightness: bool = True
    allow_media_control: bool = True
    shutdown_confirm_minutes: int = 5


_system_control_config_cache = MtimeJsonConfigCache[SystemControlConfig]()


def _load_system_control_config_uncached() -> SystemControlConfig:
    if not SYSTEM_CONTROL_CONFIG_PATH.is_file():
        return SystemControlConfig()
    try:
        raw = json.loads(SYSTEM_CONTROL_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return SystemControlConfig()
    if not isinstance(raw, dict):
        return SystemControlConfig()
    return SystemControlConfig(
        enabled=bool(raw.get("enabled", True)),
        use_in_chat=bool(raw.get("use_in_chat", True)),
        allow_shutdown=bool(raw.get("allow_shutdown", True)),
        allow_recycle_bin=bool(raw.get("allow_recycle_bin", True)),
        allow_volume=bool(raw.get("allow_volume", True)),
        allow_brightness=bool(raw.get("allow_brightness", True)),
        allow_media_control=bool(raw.get("allow_media_control", True)),
        shutdown_confirm_minutes=max(1, int(raw.get("shutdown_confirm_minutes", 5) or 5)),
    )


def load_system_control_config() -> SystemControlConfig:
    return _system_control_config_cache.get(
        SYSTEM_CONTROL_CONFIG_PATH,
        _load_system_control_config_uncached,
    )


def save_system_control_config(cfg: SystemControlConfig) -> None:
    SYSTEM_CONTROL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYSTEM_CONTROL_CONFIG_PATH.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _system_control_config_cache.invalidate()
