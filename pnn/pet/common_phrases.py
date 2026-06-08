"""常用短句预生成缓存（与时段问候共用 TTS 管线）。"""

from __future__ import annotations

import logging
from pathlib import Path

from pnn.characters.reply_lang import active_reply_language, normalize_reply_language
from pnn.core.paths import DATA_DIR
from pnn.pet.time_greeting import time_greeting_character_id

logger = logging.getLogger(__name__)

COMMON_PHRASES_DIR = DATA_DIR / "assets" / "common_phrases"

# phrase_id -> {display, zh, ja}
COMMON_PHRASE_CATALOG: dict[str, dict[str, str]] = {
    "here": {
        "display": "我在呢",
        "zh": "我在呢",
        "ja": "ここにいますよ",
    },
    "need_help": {
        "display": "有什么事吗？",
        "zh": "有什么事吗？",
        "ja": "何かご用ですか？",
    },
    "wait_moment": {
        "display": "稍等一下哦",
        "zh": "稍等一下哦",
        "ja": "少々お待ちくださいね",
    },
    "welcome_back": {
        "display": "欢迎回来",
        "zh": "欢迎回来",
        "ja": "おかえりなさい",
    },
}

ALL_COMMON_PHRASE_IDS = tuple(COMMON_PHRASE_CATALOG.keys())
ALL_COMMON_PHRASE_LANGS = ("zh", "ja")


def common_phrase_char_dir(char_id: str | None = None) -> Path:
    cid = time_greeting_character_id(char_id)
    d = COMMON_PHRASES_DIR / cid
    d.mkdir(parents=True, exist_ok=True)
    return d


def common_phrase_wav_path(phrase_id: str, lang: str, *, char_id: str | None = None) -> Path:
    code = normalize_reply_language(lang)
    pid = (phrase_id or "").strip()
    if pid not in COMMON_PHRASE_CATALOG:
        raise ValueError(f"未知常用句: {phrase_id!r}")
    return common_phrase_char_dir(char_id) / f"common_{pid}_{code}.wav"


def get_common_phrase(lang: str | None, phrase_id: str) -> tuple[str, str]:
    """返回 (气泡 display, TTS 文本)。"""
    pid = (phrase_id or "").strip()
    entry = COMMON_PHRASE_CATALOG.get(pid)
    if entry is None:
        raise ValueError(f"未知常用句: {phrase_id!r}")
    code = normalize_reply_language(lang or active_reply_language())
    display = (entry.get("display") or entry.get(code) or entry.get("zh") or "").strip()
    tts = (entry.get(code) or entry.get("zh") or display).strip()
    return display, tts


def load_common_phrase_wav(phrase_id: str, lang: str, *, char_id: str | None = None) -> bytes | None:
    path = common_phrase_wav_path(phrase_id, lang, char_id=char_id)
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data if len(data) >= 44 else None


def ensure_common_phrase_wav(api, phrase_id: str, lang: str | None = None, *, char_id: str | None = None) -> bytes:
    from pnn.pet.time_greeting import _synthesize_greeting_wav

    code = normalize_reply_language(lang or active_reply_language())
    cached = load_common_phrase_wav(phrase_id, code, char_id=char_id)
    if cached:
        return cached
    _display, tts_text = get_common_phrase(code, phrase_id)
    wav = _synthesize_greeting_wav(api, tts_text, code)
    path = common_phrase_wav_path(phrase_id, code, char_id=char_id)
    path.write_bytes(wav)
    meta = path.with_suffix(".wav.meta.txt")
    try:
        meta.write_text(tts_text, encoding="utf-8")
    except OSError:
        pass
    logger.info("常用句已写入 %s", path)
    return wav


def regenerate_all_common_phrase_wavs(
    api,
    *,
    character_ids: list[str] | None = None,
) -> dict[str, Path]:
    from pnn.pet.time_greeting import list_time_greeting_character_ids

    ids = character_ids or list_time_greeting_character_ids()
    prev = None
    try:
        from pnn.characters.service import character_pack_service

        character_pack_service.ensure_migrated()
        prev = character_pack_service.get_active_id()
    except Exception:
        prev = None
    out: dict[str, Path] = {}
    for cid in ids:
        try:
            api.set_active_character(cid)
        except Exception as exc:
            logger.warning("切换角色 %s 失败: %s", cid, exc)
        for pid in ALL_COMMON_PHRASE_IDS:
            for lang in ALL_COMMON_PHRASE_LANGS:
                ensure_common_phrase_wav(api, pid, lang, char_id=cid)
                key = f"{cid}/{pid}_{lang}"
                out[key] = common_phrase_wav_path(pid, lang, char_id=cid)
    if prev:
        try:
            api.set_active_character(prev)
        except Exception:
            pass
    return out
