from __future__ import annotations

import json
import logging
from pathlib import Path

from pnn.core.paths import DATA_DIR
from pnn.pet.reminders.models import Reminder

logger = logging.getLogger(__name__)

_DEFAULT_PATH = DATA_DIR / "reminders" / "reminders.json"


def reminders_file() -> Path:
    return _DEFAULT_PATH


def load_reminders(path: Path | None = None) -> list[Reminder]:
    p = path or reminders_file()
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("读取提醒文件失败: %s", p)
        return []
    items = raw if isinstance(raw, list) else raw.get("reminders", [])
    out: list[Reminder] = []
    for item in items:
        try:
            out.append(Reminder.model_validate(item))
        except Exception:
            logger.exception("跳过无效提醒条目: %r", item)
    return out


def save_reminders(reminders: list[Reminder], path: Path | None = None) -> None:
    p = path or reminders_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = [r.model_dump(mode="json") for r in reminders]
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
