from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from pnn.core.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

CHARACTER_CONFIG_DIR = PROJECT_ROOT / "data" / "config"
RESERVED_CONFIG_JSON = frozenset({"llm.json", "tts.json", "asr.json"})
_SAFE_ID = re.compile(r"^[\w\u4e00-\u9fff\-]+$", re.UNICODE)

_list_cache_lock = threading.RLock()
_list_cache_mtime: float = -1.0
_list_cache_items: list[dict[str, str]] | None = None


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


def invalidate_character_list_cache() -> None:
    global _list_cache_mtime, _list_cache_items
    with _list_cache_lock:
        _list_cache_mtime = -1.0
        _list_cache_items = None


def _characters_tree_mtime() -> float:
    mt = 0.0
    try:
        from pnn.characters.pack import CHARACTERS_ROOT, PACK_FILENAME, list_pack_ids, pack_path

        if CHARACTERS_ROOT.is_dir():
            for cid in list_pack_ids():
                try:
                    mt = max(mt, pack_path(cid).stat().st_mtime)
                except OSError:
                    pass
    except Exception:
        pass
    if CHARACTER_CONFIG_DIR.is_dir():
        for path in CHARACTER_CONFIG_DIR.glob("*.json"):
            if path.name in RESERVED_CONFIG_JSON:
                continue
            try:
                mt = max(mt, path.stat().st_mtime)
            except OSError:
                pass
    return mt


def _pack_list_item(char_id: str) -> dict[str, str] | None:
    """仅读 pack.json 的 id/name，避免 load_pack 的 prompt 等额外 I/O。"""
    try:
        from pnn.characters.pack import pack_path

        path = pack_path(char_id)
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        pid = str(raw.get("id") or char_id).strip() or char_id
        name = str(raw.get("name") or pid).strip() or pid
        return {"id": pid, "name": name}
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None


def _legacy_character_list_item(char_id: str) -> dict[str, str] | None:
    path = _character_path(char_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    cid = _safe_character_id(char_id)
    name = str(raw.get("name") or cid).strip() or cid
    return {"id": cid, "name": name}


def _build_character_list() -> list[dict[str, str]]:
    try:
        from pnn.characters.pack import list_pack_ids

        pack_items: list[dict[str, str]] = []
        seen: set[str] = set()
        for cid in list_pack_ids():
            item = _pack_list_item(cid)
            if item:
                pack_items.append(item)
                seen.add(item["id"])
        if pack_items:
            legacy: list[dict[str, str]] = []
            CHARACTER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            for path in sorted(CHARACTER_CONFIG_DIR.glob("*.json")):
                if path.name in RESERVED_CONFIG_JSON:
                    continue
                if path.stem in seen:
                    continue
                item = _legacy_character_list_item(path.stem)
                if item:
                    legacy.append(item)
            return pack_items + legacy
    except Exception:
        pass

    CHARACTER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, str]] = []
    for path in sorted(CHARACTER_CONFIG_DIR.glob("*.json")):
        if path.name in RESERVED_CONFIG_JSON:
            continue
        item = _legacy_character_list_item(path.stem)
        if item:
            items.append(item)
    return items


def list_characters() -> list[dict[str, str]]:
    global _list_cache_mtime, _list_cache_items
    mt = _characters_tree_mtime()
    with _list_cache_lock:
        if _list_cache_items is not None and mt == _list_cache_mtime:
            return [dict(item) for item in _list_cache_items]
        items = _build_character_list()
        _list_cache_items = [dict(item) for item in items]
        _list_cache_mtime = mt
        return [dict(item) for item in items]


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
    invalidate_character_list_cache()
    return CharacterConfig(id=cid, name=payload["name"], character_prompt=payload["character_prompt"])


def delete_character(char_id: str) -> bool:
    path = _character_path(char_id)
    if not path.is_file():
        return False
    path.unlink()
    invalidate_character_list_cache()
    return True
