from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from pnn.core.env import load_env
from pnn.core.paths import CONFIG_DIR

TRANSLATE_CONFIG_PATH = CONFIG_DIR / "translate.json"


@dataclass
class TranslateConfig:
    enabled: bool = False
    provider: str = "baidu"
    app_id: str = ""
    secret: str = ""
    from_lang: str = "jp"
    to_lang: str = "zh"


def load_translate_config() -> TranslateConfig:
    load_env()
    cfg = TranslateConfig()
    if TRANSLATE_CONFIG_PATH.is_file():
        try:
            raw = json.loads(TRANSLATE_CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = TranslateConfig(
                enabled=bool(raw.get("enabled", cfg.enabled)),
                provider=str(raw.get("provider", cfg.provider)),
                app_id=str(raw.get("app_id", cfg.app_id)),
                secret=str(raw.get("secret", cfg.secret)),
                from_lang=str(raw.get("from_lang", cfg.from_lang)),
                to_lang=str(raw.get("to_lang", cfg.to_lang)),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    if not cfg.app_id.strip():
        cfg.app_id = os.getenv("BAIDU_TRANSLATE_APP_ID", "").strip()
    if not cfg.secret.strip():
        cfg.secret = os.getenv("BAIDU_TRANSLATE_SECRET", "").strip()
    return cfg


def save_translate_config(config: TranslateConfig) -> None:
    TRANSLATE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRANSLATE_CONFIG_PATH.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
