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
class TimeGreetingSlotTexts:
    display: str = ""
    zh: str = ""
    ja: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TimeGreetingSlotTexts:
        if not raw:
            return cls()
        return cls(
            display=str(raw.get("display", "")),
            zh=str(raw.get("zh", "")),
            ja=str(raw.get("ja", "")),
        )

    def has_content(self) -> bool:
        return bool(self.display.strip() or self.zh.strip() or self.ja.strip())

    def to_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.display.strip():
            out["display"] = self.display.strip()
        if self.zh.strip():
            out["zh"] = self.zh.strip()
        if self.ja.strip():
            out["ja"] = self.ja.strip()
        return out


@dataclass
class TimeGreetingSettings:
    """时段问候：称呼与可选分时段全文覆盖（见 pack.json → time_greetings）。"""

    address_zh: str = ""
    address_ja: str = ""
    slots: dict[str, TimeGreetingSlotTexts] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TimeGreetingSettings:
        if not raw:
            return cls()
        slots: dict[str, TimeGreetingSlotTexts] = {}
        slots_raw = raw.get("slots")
        if isinstance(slots_raw, dict):
            for key, val in slots_raw.items():
                if isinstance(val, dict):
                    slots[str(key)] = TimeGreetingSlotTexts.from_dict(val)
        for key in ("morning", "noon", "evening"):
            if key in raw and isinstance(raw[key], dict):
                slots[key] = TimeGreetingSlotTexts.from_dict(raw[key])
        address_zh = str(raw.get("address_zh") or raw.get("address") or "")
        return cls(
            address_zh=address_zh,
            address_ja=str(raw.get("address_ja", "")),
            slots=slots,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.address_zh.strip():
            out["address_zh"] = self.address_zh.strip()
        if self.address_ja.strip():
            out["address_ja"] = self.address_ja.strip()
        slot_dict = {
            k: v.to_dict() for k, v in self.slots.items() if v.has_content()
        }
        if slot_dict:
            out["slots"] = slot_dict
        return out


@dataclass
class Live2DVariant:
    name: str
    dir: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Live2DVariant:
        return cls(name=str(raw.get("name", "")), dir=str(raw.get("dir", "")))

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "dir": self.dir}


@dataclass
class CharacterPack:
    id: str
    name: str = ""
    character_prompt: str = ""
    live2d_model_dir: str = "live2d/14酱"
    live2d_variants: list[Live2DVariant] = field(default_factory=list)
    tts: TtsPackSettings = field(default_factory=TtsPackSettings)
    memory_core_card: str = ""
    test_mode: bool = False
    reply_language: str = "ja"
    time_greetings: TimeGreetingSettings = field(default_factory=TimeGreetingSettings)

    def resolve_live2d_dir(self, variant_dir: str = "") -> Path:
        raw = (variant_dir or self.live2d_model_dir or "").strip()
        p = Path(raw)
        if p.is_absolute():
            return p
        return (PROJECT_ROOT / raw).resolve()

    def to_dict(self) -> dict[str, Any]:
        live2d: dict[str, Any] = {"model_dir": self.live2d_model_dir}
        if self.live2d_variants:
            live2d["variants"] = [v.to_dict() for v in self.live2d_variants]
        body: dict[str, Any] = {
            "id": self.id,
            "name": self.name or self.id,
            "character_prompt": self.character_prompt,
            "live2d": live2d,
            "tts": asdict(self.tts),
            "memory": {
                "core_card": self.memory_core_card,
                "test_mode": bool(self.test_mode),
            },
            "reply_language": self.reply_language,
        }
        tg = self.time_greetings.to_dict()
        if tg:
            body["time_greetings"] = tg
        return body

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CharacterPack:
        live2d = raw.get("live2d") or {}
        mem = raw.get("memory") or {}
        cid = str(raw.get("id", "")).strip()
        variants_raw = live2d.get("variants") or []
        return cls(
            id=cid,
            name=str(raw.get("name", cid)),
            character_prompt=str(raw.get("character_prompt", "")),
            live2d_model_dir=str(
                live2d.get("model_dir") or raw.get("live2d_model_dir") or "live2d/14酱"
            ),
            live2d_variants=[Live2DVariant.from_dict(v) for v in variants_raw],
            tts=TtsPackSettings.from_dict(raw.get("tts")),
            memory_core_card=str(mem.get("core_card", raw.get("memory_core_card", ""))),
            test_mode=bool(mem.get("test_mode", raw.get("test_mode", False))),
            reply_language=str(raw.get("reply_language", "ja")),
            time_greetings=TimeGreetingSettings.from_dict(raw.get("time_greetings")),
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
    try:
        from pnn.tts.character_layout import read_prompt_text

        stored = read_prompt_text(pack.id)
        if stored:
            pack.tts.prompt_text = stored
    except ImportError:
        pass
    return pack


def save_pack(pack: CharacterPack) -> CharacterPack:
    cid = _safe_id(pack.id)
    pack.id = cid
    try:
        from pnn.tts.character_layout import normalize_tts_pack_settings, write_prompt_text

        pack.tts = normalize_tts_pack_settings(pack.tts, cid)
        if pack.tts.prompt_text:
            write_prompt_text(cid, pack.tts.prompt_text)
    except ImportError:
        pass
    d = pack_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    pack_path(cid).write_text(
        json.dumps(pack.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        from pnn.llm.character_store import invalidate_character_list_cache

        invalidate_character_list_cache()
    except ImportError:
        pass
    try:
        from pnn.tts.service import tts_service

        tts_service.invalidate_config_cache()
    except ImportError:
        pass
    return pack
