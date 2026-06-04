"""截图识别提示：气泡文案 + 按角色语言的 TTS 缓存。"""

from __future__ import annotations

import re
from pathlib import Path

from pnn.characters.reply_lang import active_reply_language, normalize_reply_language
from pnn.core.paths import DATA_DIR
from pnn.core.audio_cache import AUDIO_CACHE_DIR, ensure_audio_cache_dir
from pnn.tts.text_sanitize import split_for_tts

# 固定提示语缓存目录（不参与 TTS 运行时缓存清理，文件一旦生成就不会覆盖）
SCREENSHOT_HINT_CACHE_DIR = DATA_DIR / "cache" / "screenshot_hints"

# 气泡显示（中文界面统一用中文）
_SCREENSHOT_HINT_DISPLAY = "主人，我已识别到截图"

# TTS 合成文案（随 reply_language；与气泡展示可略有差异，更口语化）
_SCREENSHOT_HINT_TTS: dict[str, str] = {
    "zh": "主人，我已经识别到您的截图了",
    "ja": "ご主人様、スクリーンショットを認識しました",
}

# 兼容旧引用
SCREENSHOT_HINT_TEXT = _SCREENSHOT_HINT_DISPLAY
SCREENSHOT_HINT_DISPLAY_ZH = _SCREENSHOT_HINT_DISPLAY


def format_analysis_for_tts(
    analysis: str,
    lang: str | None = None,
    *,
    max_chars: int = 800,
) -> str:
    """识图摘要 → TTS 朗读文案（日语角色会先译成日语）。"""
    body = (analysis or "").strip().replace("\n", "，")
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
    """识图摘要分句 → [(气泡展示句, TTS 合成句), ...]。"""
    body = (analysis or "").strip().replace("\n", "，")
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
    """识图完成后气泡：展示完整摘要（过长才截断）。"""
    body = (analysis or "").strip()
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
    display, _ = get_screenshot_hint(lang)
    body = (analysis or "").strip()
    if not body:
        return display
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return f"{display}\n{body}"


def get_screenshot_hint(lang: str | None = None) -> tuple[str, str]:
    """返回 (气泡显示文案, TTS 合成文案)。"""
    code = normalize_reply_language(lang or active_reply_language())
    display = _SCREENSHOT_HINT_DISPLAY
    tts = _SCREENSHOT_HINT_TTS.get(code) or _SCREENSHOT_HINT_TTS.get("zh", display)
    return display, tts


def screenshot_hint_wav_name(lang: str | None = None) -> str:
    code = normalize_reply_language(lang or active_reply_language())
    return f"screenshot_recognized_{code}.wav"


def _ensure_hint_cache_dir() -> Path:
    SCREENSHOT_HINT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOT_HINT_CACHE_DIR


def _hint_cache_paths(lang: str | None = None) -> list[Path]:
    code = normalize_reply_language(lang or active_reply_language())
    name = f"screenshot_recognized_{code}.wav"
    return [_ensure_hint_cache_dir() / name, AUDIO_CACHE_DIR / name]


def screenshot_hint_wav_path(lang: str | None = None) -> Path:
    code = normalize_reply_language(lang or active_reply_language())
    name = f"screenshot_recognized_{code}.wav"
    new_path = _ensure_hint_cache_dir() / name
    if new_path.is_file():
        return new_path
    legacy = AUDIO_CACHE_DIR / name
    if legacy.is_file():
        return legacy
    return new_path


def delete_screenshot_hint_cache(lang: str | None = None) -> int:
    """删除指定语言或全部语言的提示语缓存（含旧目录与 meta）。"""
    codes = [normalize_reply_language(lang)] if lang else ["zh", "ja"]
    removed = 0
    for code in codes:
        for path in _hint_cache_paths(code):
            for candidate in (path, path.with_suffix(".wav.meta.txt")):
                if candidate.is_file():
                    try:
                        candidate.unlink()
                        removed += 1
                    except OSError:
                        pass
    return removed


def regenerate_screenshot_hint_wav(api, lang: str) -> bytes:
    """删除旧缓存并按当前 TTS 文案重新合成。"""
    code = normalize_reply_language(lang)
    delete_screenshot_hint_cache(code)
    return ensure_screenshot_hint_wav(api, code)


def regenerate_all_screenshot_hint_wavs(api) -> dict[str, Path]:
    """重新合成中文与日语版截图提示语音。"""
    out: dict[str, Path] = {}
    for code in ("zh", "ja"):
        regenerate_screenshot_hint_wav(api, code)
        out[code] = screenshot_hint_wav_path(code)
    return out


def load_screenshot_hint_wav(lang: str | None = None) -> bytes | None:
    path = screenshot_hint_wav_path(lang)
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data if len(data) > 44 else None


def save_screenshot_hint_wav(data: bytes, lang: str | None = None) -> Path:
    path = screenshot_hint_wav_path(lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def ensure_screenshot_hint_wav(api, lang: str | None = None) -> bytes:
    """读取本地固定缓存；仅当文件不存在时才合成一次并写入（已有文件绝不覆盖）。"""
    code = normalize_reply_language(lang or active_reply_language())
    cached = load_screenshot_hint_wav(code)
    if cached:
        return cached
    _display, tts_text = get_screenshot_hint(code)
    wav = api.synthesize_tts(tts_text, text_lang=code)
    if not wav or len(wav) < 44:
        raise RuntimeError("截图提示语音合成失败")
    path = screenshot_hint_wav_path(code)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav)
    meta = path.with_suffix(".wav.meta.txt")
    try:
        meta.write_text(tts_text, encoding="utf-8")
    except OSError:
        pass
    return wav
