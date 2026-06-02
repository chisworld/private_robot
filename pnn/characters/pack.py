from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pnn.core.paths import PROJECT_ROOT

CHARACTERS_ROOT = PROJECT_ROOT / "data" / "characters"
PACK_FILENAME = "pack.json"


@dataclass
class TtsPackSettings:
    ref_audio_path: str = ""
    prompt_text: str = ""
    prompt_lang: str = "ja"
    text_lang: str = "ja"
    gpt_model_path: str = ""
    sovits_model_path: str = ""
    speed_factor: float = 1.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TtsPackSettings:
        if not raw:
            return cls()
        return cls(
            ref_audio_path=str(raw.get("ref_audio_path", "")),
            prompt_text=str(raw.get("prompt_text", "")),
            prompt_lang=str(raw.get("prompt_lang", "ja")),
            text_lang=str(raw.get("text_lang", "ja")),
            gpt_model_path=str(raw.get("gpt_model_path", "")),
            sovits_model_path=str(raw.get("sovits_model_path", "")),
            speed_factor=float(raw.get("speed_factor", 1.0)),
        )


@dataclass
class CharacterPack:
    id: str
    name: str = ""
    character_prompt: str = ""
    live2d_model_dir: str = "live2d/14酱"
    tts: TtsPackSettings = field(default_factory=TtsPackSettings)
    memory_core_card: str = ""
    reply_language: str = "ja"

    def resolve_live2d_dir(self) -> Path:
        raw = (self.live2d_model_dir or "").strip()
        p = Path(raw)
        if p.is_absolute():
            return p
        return (PROJECT_ROOT / raw).resolve()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "character_prompt": self.character_prompt,
            "live2d": {"model_dir": self.live2d_model_dir},
            "tts": asdict(self.tts),
            "memory": {"core_card": self.memory_core_card},
            "reply_language": self.reply_language,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CharacterPack:
        live2d = raw.get("live2d") or {}
        mem = raw.get("memory") or {}
        cid = str(raw.get("id", "")).strip()
        return cls(
            id=cid,
            name=str(raw.get("name", cid)),
            character_prompt=str(raw.get("character_prompt", "")),
            live2d_model_dir=str(
                live2d.get("model_dir") or raw.get("live2d_model_dir") or "live2d/14酱"
            ),
            tts=TtsPackSettings.from_dict(raw.get("tts")),
            memory_core_card=str(mem.get("core_card", raw.get("memory_core_card", ""))),
            reply_language=str(raw.get("reply_language", "ja")),
        )


def _safe_id(char_id: str) -> str:
    cid = (char_id or "").strip()
    if not cid or not re.match(r"^[\w\u4e00-\u9fff\-]+$", cid, re.UNICODE):
        raise ValueError("角色 ID 无效")
    return cid


def pack_dir(char_id: str) -> Path:
    return CHARACTERS_ROOT / _safe_id(char_id)


def pack_path(char_id: str) -> Path:
    return pack_dir(char_id) / PACK_FILENAME


def list_pack_ids() -> list[str]:
    if not CHARACTERS_ROOT.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(CHARACTERS_ROOT.iterdir()):
        if path.is_dir() and (path / PACK_FILENAME).is_file():
            ids.append(path.name)
    return ids


def load_pack(char_id: str) -> CharacterPack | None:
    path = pack_path(char_id)
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("pack.json 格式错误")
    pack = CharacterPack.from_dict(raw)
    pack.id = _safe_id(pack.id or char_id)
    return pack


def save_pack(pack: CharacterPack) -> CharacterPack:
    cid = _safe_id(pack.id)
    pack.id = cid
    d = pack_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    pack_path(cid).write_text(
        json.dumps(pack.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return pack
