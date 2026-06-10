"""剪贴板管家配置 data/config/clipboard.json"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pnn.core.paths import PROJECT_ROOT

CLIPBOARD_CONFIG_PATH = PROJECT_ROOT / "data" / "config" / "clipboard.json"
LOCAL_SERVER_ID = "local"
READ_CLIPBOARD_TOOL = "read_clipboard_text"


@dataclass
class ClipboardConfig:
    enabled: bool = True
    use_in_chat: bool = True
    max_chars: int = 12000


def load_clipboard_config() -> ClipboardConfig:
    if not CLIPBOARD_CONFIG_PATH.is_file():
        return ClipboardConfig()
    try:
        raw = json.loads(CLIPBOARD_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ClipboardConfig()
    if not isinstance(raw, dict):
        return ClipboardConfig()
    return ClipboardConfig(
        enabled=bool(raw.get("enabled", True)),
        use_in_chat=bool(raw.get("use_in_chat", True)),
        max_chars=max(500, int(raw.get("max_chars", 12000) or 12000)),
    )


def save_clipboard_config(cfg: ClipboardConfig) -> None:
    CLIPBOARD_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLIPBOARD_CONFIG_PATH.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
