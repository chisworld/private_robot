"""桌宠 UI 偏好（本地 JSON，不经过 API）。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, replace
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
    character_width_px: int = 0  # 0 = 自动按宽高比计算
    character_height_px: int = 0  # 0 = 自动按宽高比计算
    fill_percent: float = 165.0
    crop_shrink_percent: float = 45.0
    bubble_v_center_percent: float = 25.0
    bubble_gap_px: int = 10
    asr_always_on: bool = False
    voice_output_enabled: bool = True
    text_only_mode: bool = False
    tts_speak_mode: str = "sentence"  # 仅分句朗读（整段已移除）
    stream_bubble_output: bool = False  # 气泡流式输出开关
    bubble_window_x: int = -1
    bubble_window_y: int = -1
    bubble_window_w: int = 0
    bubble_window_h: int = 0
    character_window_x: int = -1
    character_window_y: int = -1
    chat_window_x: int = -1
    chat_window_y: int = -1
    chat_window_w: int = 0
    chat_window_h: int = 0
    live2d_variant_dir: str = ""
    idle_motion_amplitude: float = 1.0
    char_prefs: dict = field(default_factory=dict)

    def get_for_character(self, char_id: str) -> PetUiPreferences:
        """返回合并了角色特定偏好的副本；无记录则返回自身。"""
        cp = self.char_prefs.get(char_id, {}) if char_id else {}
        if not cp:
            return self
        return replace(
            self,
            character_scale=float(cp.get("character_scale", self.character_scale)),
            character_width_px=int(cp.get("character_width_px", self.character_width_px)),
            character_height_px=int(cp.get("character_height_px", self.character_height_px)),
            fill_percent=float(cp.get("fill_percent", self.fill_percent)),
            crop_shrink_percent=float(cp.get("crop_shrink_percent", self.crop_shrink_percent)),
            live2d_variant_dir=str(cp.get("live2d_variant_dir", self.live2d_variant_dir)),
        )

    def set_for_character(self, char_id: str, scale: float, fill: float, crop: float, variant_dir: str = "", *, width_px: int = 0, height_px: int = 0) -> None:
        """保存角色特定偏好。"""
        if not char_id:
            return
        self.char_prefs[char_id] = {
            "character_scale": scale,
            "character_width_px": width_px,
            "character_height_px": height_px,
            "fill_percent": fill,
            "crop_shrink_percent": crop,
            "live2d_variant_dir": variant_dir,
        }


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


def _safe_char_prefs(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for char_id, cp in raw.items():
        if not isinstance(cp, dict):
            continue
        out[str(char_id)] = {
            "character_scale": _clamp_float(cp.get("character_scale"), 1.5, CHARACTER_SCALE_MIN, CHARACTER_SCALE_MAX),
            "character_width_px": _clamp_int(cp.get("character_width_px"), 0, 0, 2000),
            "character_height_px": _clamp_int(cp.get("character_height_px"), 0, 0, 2000),
            "fill_percent": _clamp_float(cp.get("fill_percent"), 165.0, 100.0, 165.0),
            "crop_shrink_percent": _clamp_float(cp.get("crop_shrink_percent"), 45.0, 0.0, 90.0),
            "live2d_variant_dir": str(cp.get("live2d_variant_dir", "")),
        }
    return out


def _sanitize_colors(prefs: PetUiPreferences) -> PetUiPreferences:
    """修正气泡等不可读组合；对话窗文字色尊重用户选择。"""
    from PySide6.QtGui import QColor

    chat_bg = normalize_hex(prefs.chat_bg_color, fallback=_DEFAULT_CHAT_BG)
    chat_text = normalize_hex(prefs.chat_text_color, fallback=_DEFAULT_CHAT_TEXT)

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
        mode = "sentence"
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
            character_width_px=_clamp_int(raw.get("character_width_px"), d.character_width_px, 0, 2000),
            character_height_px=_clamp_int(raw.get("character_height_px"), d.character_height_px, 0, 2000),
            fill_percent=_clamp_float(raw.get("fill_percent"), d.fill_percent, 100.0, 165.0),
            crop_shrink_percent=_clamp_float(
                raw.get("crop_shrink_percent"), d.crop_shrink_percent, 0.0, 90.0
            ),
            bubble_v_center_percent=_clamp_float(
                raw.get("bubble_v_center_percent"), d.bubble_v_center_percent, 10.0, 70.0
            ),
            bubble_gap_px=_clamp_int(raw.get("bubble_gap_px"), d.bubble_gap_px, 0, 40),
            asr_always_on=bool(raw.get("asr_always_on", d.asr_always_on)),
            voice_output_enabled=bool(
                raw.get("voice_output_enabled", d.voice_output_enabled)
            ),
            text_only_mode=bool(raw.get("text_only_mode", d.text_only_mode)),
            tts_speak_mode=mode,
            stream_bubble_output=bool(raw.get("stream_bubble_output", d.stream_bubble_output)),
            bubble_window_x=_clamp_int(raw.get("bubble_window_x"), d.bubble_window_x, -1, 10000),
            bubble_window_y=_clamp_int(raw.get("bubble_window_y"), d.bubble_window_y, -1, 10000),
            bubble_window_w=_clamp_int(raw.get("bubble_window_w"), d.bubble_window_w, 0, 4000),
            bubble_window_h=_clamp_int(raw.get("bubble_window_h"), d.bubble_window_h, 0, 4000),
            character_window_x=_clamp_int(raw.get("character_window_x"), d.character_window_x, -1, 10000),
            character_window_y=_clamp_int(raw.get("character_window_y"), d.character_window_y, -1, 10000),
            chat_window_x=_clamp_int(raw.get("chat_window_x"), d.chat_window_x, -1, 10000),
            chat_window_y=_clamp_int(raw.get("chat_window_y"), d.chat_window_y, -1, 10000),
            chat_window_w=_clamp_int(raw.get("chat_window_w"), d.chat_window_w, 0, 4000),
            chat_window_h=_clamp_int(raw.get("chat_window_h"), d.chat_window_h, 0, 4000),
            live2d_variant_dir=str(raw.get("live2d_variant_dir", "")),
            idle_motion_amplitude=_clamp_float(
                raw.get("idle_motion_amplitude"), 1.0, 0.0, 3.0
            ),
            char_prefs=_safe_char_prefs(raw.get("char_prefs")),
        )
        return _sanitize_colors(prefs)
    except (json.JSONDecodeError, TypeError, ValueError):
        return PetUiPreferences()


def preferences_path() -> Path:
    return _CONFIG_PATH


def merge_preferences(base: PetUiPreferences, overlay: PetUiPreferences) -> PetUiPreferences:
    """将 overlay 合并进 base（char_prefs 深合并），不丢失磁盘上其它字段。"""
    merged = replace(
        base,
        **{k: getattr(overlay, k) for k in asdict(overlay) if k != "char_prefs"},
    )
    merged.char_prefs = dict(base.char_prefs)
    merged.char_prefs.update(overlay.char_prefs)
    return _sanitize_colors(merged)


def save_preferences(prefs: PetUiPreferences) -> None:
    prefs = _sanitize_colors(prefs)
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps(asdict(prefs), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def reset_window_layout(prefs: PetUiPreferences | None = None) -> PetUiPreferences:
    """恢复窗口默认布局（坐标 -1 表示下次启动自动摆放）。"""
    base = prefs or load_preferences()
    merged = replace(
        base,
        bubble_window_x=-1,
        bubble_window_y=-1,
        bubble_window_w=0,
        bubble_window_h=0,
        character_window_x=-1,
        character_window_y=-1,
        chat_window_x=-1,
        chat_window_y=-1,
        chat_window_w=0,
        chat_window_h=0,
    )
    save_preferences(merged)
    return merged


def patch_preferences(**updates) -> PetUiPreferences:
    """从磁盘加载后合并局部字段再写回，避免覆盖其它已存偏好。"""
    allowed = {f.name for f in fields(PetUiPreferences)}
    base = load_preferences()
    merged = replace(base, **{k: v for k, v in updates.items() if k in allowed})
    save_preferences(merged)
    return merged
