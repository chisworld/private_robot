"""代码/写作陪伴配置 data/config/companion.json"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pnn.core.paths import PROJECT_ROOT

COMPANION_CONFIG_PATH = PROJECT_ROOT / "data" / "config" / "companion.json"


@dataclass
class CompanionConfig:
    enabled: bool = True
    build_watch_enabled: bool = True
    writing_nudge_enabled: bool = True
    # 要监听的构建日志路径（可多个）
    build_log_paths: list[str] = field(default_factory=list)
    build_poll_seconds: int = 3
    writing_idle_minutes: int = 8
    writing_poll_seconds: int = 60
    compile_cooldown_seconds: int = 90


def load_companion_config() -> CompanionConfig:
    if not COMPANION_CONFIG_PATH.is_file():
        return CompanionConfig()
    try:
        raw = json.loads(COMPANION_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return CompanionConfig()
    if not isinstance(raw, dict):
        return CompanionConfig()
    paths = raw.get("build_log_paths") or []
    if not isinstance(paths, list):
        paths = []
    return CompanionConfig(
        enabled=bool(raw.get("enabled", True)),
        build_watch_enabled=bool(raw.get("build_watch_enabled", True)),
        writing_nudge_enabled=bool(raw.get("writing_nudge_enabled", True)),
        build_log_paths=[str(p).strip() for p in paths if str(p).strip()],
        build_poll_seconds=max(2, int(raw.get("build_poll_seconds", 3) or 3)),
        writing_idle_minutes=max(3, int(raw.get("writing_idle_minutes", 8) or 8)),
        writing_poll_seconds=max(30, int(raw.get("writing_poll_seconds", 60) or 60)),
        compile_cooldown_seconds=max(30, int(raw.get("compile_cooldown_seconds", 90) or 90)),
    )


def save_companion_config(cfg: CompanionConfig) -> None:
    COMPANION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMPANION_CONFIG_PATH.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
