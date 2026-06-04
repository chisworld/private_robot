"""截图识别提示：气泡文案 + 按角色与语言的 TTS 缓存。"""

from __future__ import annotations

import re
from pathlib import Path

from pnn.characters.reply_lang import active_reply_language, normalize_reply_language
from pnn.core.audio_cache import AUDIO_CACHE_DIR
from pnn.tts.character_layout import (
    _LEGACY_SCREENSHOT_HINTS,
    active_character_id,
    list_character_ids,
    screenshot_hints_dir,
)
from pnn.tts.text_sanitize import split_for_tts

# 兼容旧 import
SCREENSHOT_HINT_CACHE_DIR = _LEGACY_SCREENSHOT_HINTS

# 气泡显示（中文界面统一用中文）
_SCREENSHOT_HINT_DISPLAY = "主人，我已识别到截图"

# TTS 合成文案（随 reply_language；与气泡展示可略有差异，更口语化）
_SCREENSHOT_HINT_TTS: dict[str, str] = {
    "zh": "主人，我已经识别到您的截图了",
    "ja": "ご主人様、スクリーンショットを認識しました",
}

# 角色专属截图提示（未列出的角色用默认「主人」）
_CHARACTER_SCREENSHOT_HINTS: dict[str, dict[str, str]] = {
    "里想奈": {
        "display": "哥哥，我已识别到截图",
        "zh": "哥哥，我已经识别到你的截图了",
        "ja": "お兄ちゃん、スクリーンショットを認識しました",
    },
}

# 兼容旧引用
SCREENSHOT_HINT_TEXT = _SCREENSHOT_HINT_DISPLAY
SCREENSHOT_HINT_DISPLAY_ZH = _SCREENSHOT_HINT_DISPLAY


def all_screenshot_hint_displays() -> frozenset[str]:
    """各角色截图固定提示气泡文案（用于去重判断）。"""
    texts = {_SCREENSHOT_HINT_DISPLAY}
    for entry in _CHARACTER_SCREENSHOT_HINTS.values():
        d = (entry.get("display") or "").strip()
        if d:
            texts.add(d)
    return frozenset(texts)


def analysis_for_bubble_display(analysis: str) -> str:
    """识图原文（可能为日文）→ 气泡统一展示的简体中文。"""
    from pnn.pet.expression_tags import strip_expression_tags
    from pnn.translate.service import translate_service

    body = strip_expression_tags((analysis or "").strip())
    if not body:
        return ""
    return translate_service.to_bubble_chinese(body)


def format_analysis_for_tts(
    analysis: str,
    lang: str | None = None,
    *,
    max_chars: int = 800,
) -> str:
    """识图摘要 → TTS 朗读文案（日语角色会先译成日语）。"""
    body = analysis_for_bubble_display(analysis).replace("\n", "，")
    body = re.sub(r"，+", "，", body).strip("，")
    body = body.replace("「", "").replace("」", "")
    if not body:
        return ""
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    code = normalize_reply_language(lang or active_reply_language())
    if code == "ja":
        from pnn.translate.service import translate_service

        body = translate_service.chinese_to_japanese(body)
    body = body.replace("\n", "，").replace("「", "").replace("」", "")
    return body


def format_analysis_segments(
    analysis: str,
    lang: str | None = None,
    *,
    max_chars: int = 120,
) -> list[tuple[str, str]]:
    """识图摘要分句 → [(气泡展示句中文, TTS 合成句), ...]。"""
    body = analysis_for_bubble_display(analysis).replace("\n", "，")
    body = re.sub(r"，+", "，", body).strip("，")
    body = body.replace("「", "").replace("」", "")
    if not body:
        return []
    code = normalize_reply_language(lang or active_reply_language())
    zh_parts = split_for_tts(body, max_chars=max_chars)
    if code == "ja":
        from pnn.translate.service import translate_service

        out: list[tuple[str, str]] = []
        for part in zh_parts:
            tts = translate_service.chinese_to_japanese(part)
            tts = tts.replace("\n", "，").replace("「", "").replace("」", "").strip()
            if tts:
                out.append((part, tts))
        return out
    return [(part, part) for part in zh_parts]


def format_screenshot_analysis_bubble(
    analysis: str,
    *,
    max_chars: int = 4000,
) -> str:
    """识图完成后气泡：展示完整摘要（界面统一中文，过长才截断）。"""
    body = analysis_for_bubble_display(analysis)
    if not body:
        return _SCREENSHOT_HINT_DISPLAY
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return body


def format_screenshot_recognition_bubble(
    analysis: str,
    lang: str | None = None,
    *,
    max_chars: int = 480,
) -> str:
    """气泡：固定提示 + 识图摘要。"""
    display, _ = get_screenshot_hint(lang, char_id=active_character_id())
    body = analysis_for_bubble_display(analysis)
    if not body:
        return display
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return f"{display}\n{body}"


def get_screenshot_hint(
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> tuple[str, str]:
    """返回 (气泡显示文案, TTS 合成文案)。"""
    code = normalize_reply_language(lang or active_reply_language())
    cid = (char_id or active_character_id()).strip()
    custom = _CHARACTER_SCREENSHOT_HINTS.get(cid)
    if custom:
        display = (custom.get("display") or _SCREENSHOT_HINT_DISPLAY).strip()
        tts = (custom.get(code) or custom.get("zh") or display).strip()
        return display, tts
    display = _SCREENSHOT_HINT_DISPLAY
    tts = _SCREENSHOT_HINT_TTS.get(code) or _SCREENSHOT_HINT_TTS.get("zh", display)
    return display, tts


def screenshot_hint_wav_name(lang: str | None = None) -> str:
    code = normalize_reply_language(lang or active_reply_language())
    return f"screenshot_recognized_{code}.wav"


def _wav_basename(lang: str) -> str:
    code = normalize_reply_language(lang)
    return f"screenshot_recognized_{code}.wav"


def screenshot_hint_wav_path(
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> Path:
    """标准路径：data/assets/screenshot_hints/{角色ID}/screenshot_recognized_{lang}.wav"""
    code = normalize_reply_language(lang or active_reply_language())
    return screenshot_hints_dir(char_id) / _wav_basename(code)


def _hint_cache_paths(
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> list[Path]:
    code = normalize_reply_language(lang or active_reply_language())
    name = _wav_basename(code)
    cid = char_id or active_character_id()
    ordered = [
        screenshot_hints_dir(cid) / name,
        _LEGACY_SCREENSHOT_HINTS / name,
        AUDIO_CACHE_DIR / name,
    ]
    seen: set[Path] = set()
    out: list[Path] = []
    for p in ordered:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def resolve_screenshot_hint_wav_path(
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> Path | None:
    for path in _hint_cache_paths(lang, char_id=char_id):
        if path.is_file():
            return path
    return None


def delete_screenshot_hint_cache(
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> int:
    """删除指定语言或全部语言的提示语缓存（含旧目录与 meta）。"""
    codes = [normalize_reply_language(lang)] if lang else ["zh", "ja"]
    removed = 0
    for code in codes:
        for path in _hint_cache_paths(code, char_id=char_id):
            for candidate in (path, path.with_suffix(".wav.meta.txt")):
                if candidate.is_file():
                    try:
                        candidate.unlink()
                        removed += 1
                    except OSError:
                        pass
    return removed


def regenerate_screenshot_hint_wav(
    api,
    lang: str,
    *,
    char_id: str | None = None,
) -> bytes:
    """删除旧缓存并按当前 TTS 文案重新合成。"""
    code = normalize_reply_language(lang)
    delete_screenshot_hint_cache(code, char_id=char_id)
    return ensure_screenshot_hint_wav(api, code, char_id=char_id)


def regenerate_all_screenshot_hint_wavs(
    api,
    *,
    character_ids: list[str] | None = None,
) -> dict[str, Path]:
    """为每个角色包重新合成中/日截图提示语音。"""
    ids = character_ids or list_character_ids()
    prev = None
    try:
        from pnn.characters.service import character_pack_service

        prev = character_pack_service.get_active_id()
    except Exception:
        pass
    out: dict[str, Path] = {}
    for cid in ids:
        try:
            api.set_active_character(cid)
        except Exception:
            pass
        for code in ("zh", "ja"):
            regenerate_screenshot_hint_wav(api, code, char_id=cid)
            out[f"{cid}/{code}"] = screenshot_hint_wav_path(code, char_id=cid)
    if prev:
        try:
            api.set_active_character(prev)
        except Exception:
            pass
    return out


def load_screenshot_hint_wav(
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> bytes | None:
    path = resolve_screenshot_hint_wav_path(lang, char_id=char_id)
    if path is None or not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data if len(data) > 44 else None


def save_screenshot_hint_wav(
    data: bytes,
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> Path:
    path = screenshot_hint_wav_path(lang, char_id=char_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def ensure_screenshot_hint_wav(
    api,
    lang: str | None = None,
    *,
    char_id: str | None = None,
) -> bytes:
    """读取本地固定缓存；仅当文件不存在时才合成一次并写入（已有文件绝不覆盖）。"""
    code = normalize_reply_language(lang or active_reply_language())
    cached = load_screenshot_hint_wav(code, char_id=char_id)
    if cached:
        return cached
    _display, tts_text = get_screenshot_hint(code, char_id=char_id)
    wav = api.synthesize_tts(tts_text, text_lang=code)
    if not wav or len(wav) < 44:
        raise RuntimeError("截图提示语音合成失败")
    path = screenshot_hint_wav_path(code, char_id=char_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav)
    meta = path.with_suffix(".wav.meta.txt")
    try:
        meta.write_text(tts_text, encoding="utf-8")
    except OSError:
        pass
    return wav
