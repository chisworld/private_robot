"""桌宠 UI 偏好（本地 JSON，不经过 API）。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from pnn.core.paths import PROJECT_ROOT
from pnn.pet.color_picker_widget import normalize_hex
from pnn.pet.ui_constants import CHARACTER_SCALE_MAX, CHARACTER_SCALE_MIN

_CONFIG_PATH = PROJECT_ROOT / "data" / "config" / "pet_ui.json"

_DEFAULT_CHAT_TEXT = "#111827"
_DEFAULT_CHAT_BG = "#f8fafc"
_DEFAULT_BUBBLE_TEXT = "#ffffff"
_DEFAULT_BUBBLE_BG = "#333333"


@dataclass
class PetUiPreferences:
    chat_font_size: int = 20
    chat_text_color: str = _DEFAULT_CHAT_TEXT
    chat_bg_color: str = _DEFAULT_CHAT_BG
    chat_bg_transparency_percent: int = 0
    chat_font_family: str = "Microsoft YaHei UI"
    bubble_font_size: int = 20
    bubble_font_family: str = "Microsoft YaHei UI"
    use_imported_font: bool = False
    bubble_width_px: int = 120
    bubble_height_px: int = 200
    bubble_text_color: str = _DEFAULT_BUBBLE_TEXT
    bubble_bg_color: str = _DEFAULT_BUBBLE_BG
    bubble_bg_transparency_percent: int = 0
    page_interval_ms: int = 2000
    character_scale: float = 1.5
    fill_percent: float = 165.0
    crop_shrink_percent: float = 45.0
    bubble_v_center_percent: float = 25.0
    bubble_gap_px: int = 10
    asr_always_on: bool = False
    tts_speak_mode: str = "full"  # sentence | full


def _clamp_int(v: object, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _clamp_float(v: object, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _sanitize_colors(prefs: PetUiPreferences) -> PetUiPreferences:
    """修正白底白字等不可读组合（常见于误点「纯白」）。"""
    from PySide6.QtGui import QColor

    chat_bg = normalize_hex(prefs.chat_bg_color, fallback=_DEFAULT_CHAT_BG)
    chat_text = normalize_hex(prefs.chat_text_color, fallback=_DEFAULT_CHAT_TEXT)
    if QColor(chat_bg).lightness() > 160 and QColor(chat_text).lightness() > 160:
        chat_text = _DEFAULT_CHAT_TEXT

    bubble_bg = normalize_hex(prefs.bubble_bg_color, fallback=_DEFAULT_BUBBLE_BG)
    bubble_text = normalize_hex(prefs.bubble_text_color, fallback=_DEFAULT_BUBBLE_TEXT)
    if QColor(bubble_bg).lightness() > 160 and QColor(bubble_text).lightness() > 160:
        bubble_bg, bubble_text = _DEFAULT_BUBBLE_BG, _DEFAULT_BUBBLE_TEXT
    if QColor(bubble_bg).lightness() < 100 and QColor(bubble_text).lightness() < 100:
        bubble_text = _DEFAULT_BUBBLE_TEXT

    return replace(
        prefs,
        chat_bg_color=chat_bg,
        chat_text_color=chat_text,
        bubble_bg_color=bubble_bg,
        bubble_text_color=bubble_text,
    )


def load_preferences() -> PetUiPreferences:
    d = PetUiPreferences()
    if not _CONFIG_PATH.is_file():
        return d
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        mode = str(raw.get("tts_speak_mode", d.tts_speak_mode)).strip().lower()
        if mode not in ("sentence", "full"):
            mode = d.tts_speak_mode
        prefs = PetUiPreferences(
            chat_font_size=_clamp_int(raw.get("chat_font_size"), d.chat_font_size, 10, 32),
            chat_text_color=str(raw.get("chat_text_color", d.chat_text_color))[:16],
            chat_bg_color=str(raw.get("chat_bg_color", d.chat_bg_color))[:16],
            chat_bg_transparency_percent=_clamp_int(
                raw.get("chat_bg_transparency_percent", d.chat_bg_transparency_percent),
                d.chat_bg_transparency_percent,
                0,
                100,
            ),
            chat_font_family=str(raw.get("chat_font_family", d.chat_font_family))[:64],
            bubble_font_size=_clamp_int(raw.get("bubble_font_size"), d.bubble_font_size, 10, 36),
            bubble_font_family=str(raw.get("bubble_font_family", d.bubble_font_family))[:64],
            use_imported_font=bool(raw.get("use_imported_font", d.use_imported_font)),
            bubble_width_px=_clamp_int(raw.get("bubble_width_px"), d.bubble_width_px, 60, 400),
            bubble_height_px=_clamp_int(raw.get("bubble_height_px"), d.bubble_height_px, 40, 500),
            bubble_text_color=str(raw.get("bubble_text_color", d.bubble_text_color))[:16],
            bubble_bg_color=str(raw.get("bubble_bg_color", d.bubble_bg_color))[:16],
            bubble_bg_transparency_percent=_clamp_int(
                raw.get(
                    "bubble_bg_transparency_percent",
                    raw.get("bubble_bg_opacity_percent", d.bubble_bg_transparency_percent),
                ),
                d.bubble_bg_transparency_percent,
                0,
                100,
            ),
            page_interval_ms=_clamp_int(raw.get("page_interval_ms"), d.page_interval_ms, 800, 15000),
            character_scale=_clamp_float(
                raw.get("character_scale"),
                d.character_scale,
                CHARACTER_SCALE_MIN,
                CHARACTER_SCALE_MAX,
            ),
            fill_percent=_clamp_float(raw.get("fill_percent"), d.fill_percent, 100.0, 165.0),
            crop_shrink_percent=_clamp_float(
                raw.get("crop_shrink_percent"), d.crop_shrink_percent, 0.0, 90.0
            ),
            bubble_v_center_percent=_clamp_float(
                raw.get("bubble_v_center_percent"), d.bubble_v_center_percent, 10.0, 70.0
            ),
            bubble_gap_px=_clamp_int(raw.get("bubble_gap_px"), d.bubble_gap_px, 0, 40),
            asr_always_on=bool(raw.get("asr_always_on", d.asr_always_on)),
            tts_speak_mode=mode,
        )
        return _sanitize_colors(prefs)
    except (json.JSONDecodeError, TypeError, ValueError):
        return PetUiPreferences()


def save_preferences(prefs: PetUiPreferences) -> None:
    prefs = _sanitize_colors(prefs)
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps(asdict(prefs), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
