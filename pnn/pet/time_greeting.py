"""时段问候：早 / 中 / 晚固定语音（按角色语言 TTS，气泡统一中文）。

语音按角色分目录保存：data/assets/time_greetings/{角色ID}/time_greeting_{时段}_{语言}.wav
首次缺失时用当前角色音色合成；兼容根目录旧路径（视为塞拉）。
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from enum import Enum
from pathlib import Path

from pnn.characters.reply_lang import active_reply_language, normalize_reply_language
from pnn.core.paths import DATA_DIR

logger = logging.getLogger(__name__)

# 项目内固定资源目录（非运行时 cache，不参与 TTS 清理）
TIME_GREETING_DIR = DATA_DIR / "assets" / "time_greetings"
_LEGACY_DIR = DATA_DIR / "cache" / "time_greetings"
# 根目录平铺的旧文件为塞拉音色
_LEGACY_FLAT_OWNER = "塞拉"

_SAFE_CHAR_RE = re.compile(r"^[\w\u4e00-\u9fff\-]+$", re.UNICODE)

# 气泡展示（界面统一中文）
_GREETING_DISPLAY: dict[str, str] = {
    "morning": "早上好主人，今天也是美好的一天呢",
    "noon": "中午好主人，有没有午睡啊？下午也要元气满满哦",
    "evening": "晚上好主人，主人困了吗，我已经帮你暖好床了哦",
}

# 角色专属登录问候（气泡中文 + TTS 中/日）；未列出的角色用默认「主人」文案
_CHARACTER_GREETINGS: dict[str, dict[str, dict[str, str]]] = {
    "里想奈": {
        "morning": {
            "display": "早上好哥哥，今天也是美好的一天呢",
            "zh": "早上好哥哥，今天也是美好的一天呢",
            "ja": "おはよう、お兄ちゃん。今日も素敵な一日になりますように",
        },
        "noon": {
            "display": "中午好哥哥，有没有午睡啊？下午也要元气满满哦",
            "zh": "中午好哥哥，有没有午睡啊？下午也要元气满满哦",
            "ja": "こんにちは、お兄ちゃん。お昼寝はいかがでしたか？午後も元気いっぱいでいきましょうね",
        },
        "evening": {
            "display": "晚上好哥哥，哥哥困了吗，我已经帮你暖好床了哦",
            "zh": "晚上好哥哥，哥哥困了吗，我已经帮你暖好床了哦",
            "ja": "こんばんは、お兄ちゃん。眠くなりましたか？お布団、もう温めておきましたよ",
        },
    },
}

# TTS 合成文案（默认 / 塞拉等）
_GREETING_TTS: dict[str, dict[str, str]] = {
    "morning": {
        "zh": "早上好主人，今天也是美好的一天呢",
        "ja": "おはようございます、ご主人様。今日も素敵な一日になりますように",
    },
    "noon": {
        "zh": "中午好主人，有没有午睡啊？下午也要元气满满哦",
        "ja": "こんにちは、ご主人様。お昼寝はいかがでしたか？午後も元気いっぱいでいきましょうね",
    },
    "evening": {
        "zh": "晚上好主人，主人困了吗，我已经帮你暖好床了哦",
        "ja": "こんばんは、ご主人様。眠くなりましたか？お布団、もう温めておきましたよ",
    },
}

ALL_GREETING_LANGS = ("zh", "ja")
ALL_GREETING_SLOTS = ("morning", "noon", "evening")


class TimeSlot(str, Enum):
    MORNING = "morning"
    NOON = "noon"
    EVENING = "evening"


def list_time_greeting_character_ids() -> list[str]:
    """已配置角色包 ID 列表（用于预生成问候音）。"""
    from pnn.tts.character_layout import list_character_ids

    return list_character_ids()


def time_greeting_character_id(char_id: str | None = None) -> str:
    """问候音所属角色；默认当前激活角色。"""
    if char_id and str(char_id).strip():
        return _normalize_character_id(str(char_id))
    try:
        from pnn.characters.service import character_pack_service

        character_pack_service.ensure_migrated()
        return _normalize_character_id(character_pack_service.get_active_id())
    except Exception:
        return _LEGACY_FLAT_OWNER


def _normalize_character_id(char_id: str) -> str:
    cid = (char_id or "").strip()
    if not cid or not _SAFE_CHAR_RE.match(cid):
        raise ValueError(f"角色 ID 无效: {char_id!r}")
    return cid


def current_time_slot(now: datetime | None = None) -> TimeSlot:
    """早 5–10 时，中 11–17 时，晚 18–4 时。"""
    hour = (now or datetime.now()).hour
    if 5 <= hour < 11:
        return TimeSlot.MORNING
    if 11 <= hour < 18:
        return TimeSlot.NOON
    return TimeSlot.EVENING


def get_time_greeting(
    lang: str | None = None,
    *,
    slot: TimeSlot | None = None,
    char_id: str | None = None,
) -> tuple[str, str, TimeSlot]:
    """返回 (气泡中文, TTS 文案, 时段)。"""
    code = normalize_reply_language(lang or active_reply_language())
    period = slot or current_time_slot()
    key = period.value
    cid = time_greeting_character_id(char_id)
    custom = _CHARACTER_GREETINGS.get(cid, {}).get(key)
    if custom:
        display = custom.get("display") or custom.get("zh") or _GREETING_DISPLAY[key]
        tts = custom.get(code) or custom.get("zh") or display
        return display, tts, period
    display = _GREETING_DISPLAY[key]
    tts_map = _GREETING_TTS[key]
    tts = tts_map.get(code) or tts_map.get("zh", display)
    return display, tts, period


def _wav_basename(slot: TimeSlot | str, lang: str) -> str:
    code = normalize_reply_language(lang)
    return f"time_greeting_{_slot_key(slot)}_{code}.wav"


def _slot_key(slot: TimeSlot | str) -> str:
    return slot.value if isinstance(slot, TimeSlot) else str(slot)


def time_greeting_char_dir(char_id: str | None = None) -> Path:
    cid = time_greeting_character_id(char_id)
    path = TIME_GREETING_DIR / cid
    path.mkdir(parents=True, exist_ok=True)
    return path


def time_greeting_wav_path(
    slot: TimeSlot | str,
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> Path:
    """标准存储路径：assets/time_greetings/{角色}/time_greeting_{时段}_{语言}.wav"""
    code = normalize_reply_language(lang or active_reply_language())
    return time_greeting_char_dir(char_id) / _wav_basename(slot, code)


def _flat_assets_wav_path(slot: TimeSlot | str, lang: str | None = None) -> Path:
    """旧版根目录平铺路径（兼容读取）。"""
    code = normalize_reply_language(lang or active_reply_language())
    return TIME_GREETING_DIR / _wav_basename(slot, code)


def _legacy_cache_wav_path(slot: TimeSlot | str, lang: str | None = None) -> Path:
    code = normalize_reply_language(lang or active_reply_language())
    return _LEGACY_DIR / _wav_basename(slot, code)


def _candidate_wav_paths(
    slot: TimeSlot | str,
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> list[Path]:
    cid = time_greeting_character_id(char_id)
    ordered = [time_greeting_wav_path(slot, lang, char_id=cid)]
    # 仅塞拉可读根目录旧平铺文件，其它角色必须用自家目录（避免串音色）
    if cid == _LEGACY_FLAT_OWNER:
        ordered.append(_flat_assets_wav_path(slot, lang))
    ordered.append(_legacy_cache_wav_path(slot, lang))
    seen: set[Path] = set()
    out: list[Path] = []
    for p in ordered:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def resolve_time_greeting_wav_path(
    slot: TimeSlot | str,
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> Path | None:
    """查找已存在的 wav（优先当前角色目录，兼容根目录与 cache）。"""
    for path in _candidate_wav_paths(slot, lang, char_id=char_id):
        if path.is_file():
            return path
    return None


def load_time_greeting_wav(
    slot: TimeSlot | str,
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> bytes | None:
    path = resolve_time_greeting_wav_path(slot, lang, char_id=char_id)
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data if len(data) > 44 else None


_GREETING_TTS_SPLIT = re.compile(r"(?<=[。！？!?])")


def _tts_segments(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in _GREETING_TTS_SPLIT.split(raw) if p.strip()]
    return parts if parts else [raw]


def _synthesize_greeting_wav(api, tts_text: str, text_lang: str) -> bytes:
    """分句合成再拼接，避免 GPT-SoVITS 长句只录前半段。"""
    from pnn.pet.audio import concat_wav_bytes

    segments = _tts_segments(tts_text)
    parts: list[bytes] = []
    for seg in segments:
        wav = api.synthesize_tts(seg, text_lang=text_lang)
        if not wav or len(wav) < 44:
            raise RuntimeError(f"时段问候语音合成失败: {seg[:40]}")
        parts.append(wav)
    if not parts:
        raise RuntimeError("时段问候语音合成失败")
    return concat_wav_bytes(parts) if len(parts) > 1 else parts[0]


def _unlink_greeting_files(*paths: Path) -> None:
    for path in paths:
        for candidate in (path, path.with_suffix(".wav.meta.txt")):
            if candidate.is_file():
                try:
                    candidate.unlink()
                except OSError:
                    pass


def ensure_time_greeting_wav(
    api,
    slot: TimeSlot | str,
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> bytes:
    """读取角色目录 wav；不存在则合成并写入（已有文件不覆盖）。"""
    code = normalize_reply_language(lang or active_reply_language())
    cached = load_time_greeting_wav(slot, code, char_id=char_id)
    if cached:
        return cached
    period = TimeSlot(_slot_key(slot))
    cid = time_greeting_character_id(char_id)
    _display, tts_text, _ = get_time_greeting(code, slot=period, char_id=cid)
    wav = _synthesize_greeting_wav(api, tts_text, code)
    path = time_greeting_wav_path(slot, code, char_id=cid)
    path.write_bytes(wav)
    meta = path.with_suffix(".wav.meta.txt")
    try:
        meta.write_text(tts_text, encoding="utf-8")
    except OSError:
        pass
    logger.info("时段问候已写入 %s", path)
    return wav


def regenerate_time_greeting_wav(
    api,
    slot: str,
    lang: str,
    *,
    char_id: str | None = None,
) -> Path:
    """删除指定角色条目并重新合成（换音色时用）。"""
    code = normalize_reply_language(lang)
    cid = time_greeting_character_id(char_id)
    to_clear = list(_candidate_wav_paths(slot, code, char_id=cid))
    to_clear.append(time_greeting_wav_path(slot, code, char_id=cid))
    _unlink_greeting_files(*to_clear)
    ensure_time_greeting_wav(api, slot, code, char_id=cid)
    return time_greeting_wav_path(slot, code, char_id=cid)


def regenerate_all_time_greeting_wavs(
    api,
    *,
    character_ids: list[str] | None = None,
) -> dict[str, Path]:
    """为每个角色包预生成全部问候语音（早/中/晚 × 中/日）。"""
    from pnn.characters.service import character_pack_service

    character_pack_service.ensure_migrated()
    ids = character_ids or list_time_greeting_character_ids()
    prev_active = character_pack_service.get_active_id()
    out: dict[str, Path] = {}
    for cid in ids:
        try:
            api.set_active_character(cid)
        except Exception as exc:
            logger.warning("切换角色 %s 失败，仍尝试合成: %s", cid, exc)
        for slot in ALL_GREETING_SLOTS:
            for lang in ALL_GREETING_LANGS:
                key = f"{cid}/{slot}_{lang}"
                regenerate_time_greeting_wav(api, slot, lang, char_id=cid)
                out[key] = time_greeting_wav_path(slot, lang, char_id=cid)
    try:
        api.set_active_character(prev_active)
    except Exception:
        pass
    return out


def migrate_flat_assets_to_character(
    owner: str = _LEGACY_FLAT_OWNER,
    *,
    remove_source: bool = True,
) -> int:
    """将 assets/time_greetings/ 根目录下的 wav 迁入指定角色子目录。"""
    if not TIME_GREETING_DIR.is_dir():
        return 0
    dest_dir = time_greeting_char_dir(owner)
    moved = 0
    for src in sorted(TIME_GREETING_DIR.glob("time_greeting_*.wav*")):
        if not src.is_file():
            continue
        target = dest_dir / src.name
        if target.is_file():
            if remove_source:
                try:
                    src.unlink()
                except OSError:
                    pass
            continue
        try:
            shutil.move(str(src), str(target))
            moved += 1
        except OSError as exc:
            logger.warning("迁移问候音失败 %s: %s", src, exc)
    return moved
