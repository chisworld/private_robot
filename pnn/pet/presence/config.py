"""在场感 / 日程提醒配置（data/config/presence.json）。"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from pnn.core.paths import CONFIG_DIR

logger = logging.getLogger(__name__)

_CONFIG_PATH = CONFIG_DIR / "presence.json"


@dataclass
class PresenceConfig:
    presence_enabled: bool = True
    presence_idle_seconds: int = 300
    presence_afk_seconds: int = 7200
    presence_poll_seconds: int = 60
    presence_idle_probability: float = 1.0
    presence_weather_enabled: bool = True
    presence_weather_city: str = ""
    presence_interrupt_window_seconds: int = 10
    presence_interrupt_message_count: int = 3
    schedule_auto_trigger_on_open: bool = True
    schedule_auto_greet_on_open: bool = True
    schedule_nudge_during_window: bool = True
    schedule_background_monitor: bool = True
    schedule_startup_delay_seconds: int = 45
    schedule_background_poll_seconds: int = 1800
    presence_boot_quiet_seconds: int = 45


def load_presence_config() -> PresenceConfig:
    if not _CONFIG_PATH.is_file():
        return PresenceConfig()
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return PresenceConfig()
        valid = {f.name for f in fields(PresenceConfig)}
        filtered = {k: v for k, v in raw.items() if k in valid}
        return PresenceConfig(**filtered)
    except Exception:
        logger.exception("读取 presence.json 失败，使用默认配置")
        return PresenceConfig()


def save_presence_config(cfg: PresenceConfig) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
