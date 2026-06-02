from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from pnn.core.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

CHARACTER_CONFIG_DIR = PROJECT_ROOT / "data" / "config"
RESERVED_CONFIG_JSON = frozenset({"llm.json", "tts.json", "asr.json"})
_SAFE_ID = re.compile(r"^[\w\u4e00-\u9fff\-]+$", re.UNICODE)


@dataclass
class CharacterConfig:
    """对应 data/config/{id}.json，仅存放人物设定。"""

    id: str
    name: str = ""
    character_prompt: str = ""


def _safe_character_id(char_id: str) -> str:
    cid = (char_id or "").strip()
    if not cid or not _SAFE_ID.match(cid):
        raise ValueError("角色 ID 无效，请使用中文/字母/数字/下划线/连字符")
    if cid.endswith(".json"):
        cid = cid[: -len(".json")]
    return cid


def _character_path(char_id: str) -> Path:
    return CHARACTER_CONFIG_DIR / f"{_safe_character_id(char_id)}.json"


def list_characters() -> list[dict[str, str]]:
    try:
        from pnn.characters.pack import list_pack_ids, load_pack

        pack_items: list[dict[str, str]] = []
        seen: set[str] = set()
        for cid in list_pack_ids():
            pack = load_pack(cid)
            if pack:
                pack_items.append({"id": pack.id, "name": pack.name or pack.id})
                seen.add(pack.id)
        if pack_items:
            legacy: list[dict[str, str]] = []
            CHARACTER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            for path in sorted(CHARACTER_CONFIG_DIR.glob("*.json")):
                if path.name in RESERVED_CONFIG_JSON:
                    continue
                if path.stem in seen:
                    continue
                try:
                    ch = load_character(path.stem)
                except (OSError, json.JSONDecodeError, ValueError):
                    continue
                if ch:
                    legacy.append({"id": ch.id, "name": ch.name or ch.id})
            return pack_items + legacy
    except Exception:
        pass

    CHARACTER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, str]] = []
    for path in sorted(CHARACTER_CONFIG_DIR.glob("*.json")):
        if path.name in RESERVED_CONFIG_JSON:
            continue
        char_id = path.stem
        try:
            ch = load_character(char_id)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("跳过无效角色文件 %s: %s", path.name, exc)
            continue
        if ch is None:
            continue
        items.append({"id": ch.id, "name": ch.name or ch.id})
    return items


def load_character(char_id: str) -> CharacterConfig | None:
    try:
        from pnn.characters.pack import load_pack

        pack = load_pack(char_id)
        if pack is not None:
            return CharacterConfig(
                id=pack.id,
                name=pack.name or pack.id,
                character_prompt=pack.character_prompt,
            )
    except Exception:
        pass
    path = _character_path(char_id)
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"角色文件格式错误: {path.name}")
    cid = _safe_character_id(char_id)
    prompt = str(raw.get("character_prompt") or raw.get("character_setting") or "").strip()
    name = str(raw.get("name") or cid).strip()
    return CharacterConfig(id=cid, name=name, character_prompt=prompt)


def save_character(config: CharacterConfig) -> CharacterConfig:
    cid = _safe_character_id(config.id)
    CHARACTER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": (config.name or cid).strip(),
        "character_prompt": config.character_prompt,
    }
    path = _character_path(cid)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return CharacterConfig(id=cid, name=payload["name"], character_prompt=payload["character_prompt"])


def delete_character(char_id: str) -> bool:
    path = _character_path(char_id)
    if not path.is_file():
        return False
    path.unlink()
    return True
