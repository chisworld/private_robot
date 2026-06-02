"""桌宠字体：系统预设 + 用户导入。"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

from pnn.core.paths import PROJECT_ROOT

_FONTS_DIR = PROJECT_ROOT / "data" / "fonts"
_IMPORTED_NAME = "imported"

_PRESET_FAMILIES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "SimSun",
    "SimHei",
    "KaiTi",
    "FangSong",
    "Segoe UI",
)


def fonts_storage_dir() -> Path:
    _FONTS_DIR.mkdir(parents=True, exist_ok=True)
    return _FONTS_DIR


def preset_families() -> list[str]:
    return list(_PRESET_FAMILIES)


def imported_font_path() -> Path | None:
    for ext in (".ttf", ".otf", ".ttc"):
        p = fonts_storage_dir() / f"{_IMPORTED_NAME}{ext}"
        if p.is_file():
            return p
    return None


def register_imported_font() -> str | None:
    """注册导入字体，返回 Qt family 名。"""
    path = imported_font_path()
    if path is None:
        return None
    fid = QFontDatabase.addApplicationFont(str(path))
    if fid < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(fid)
    return families[0] if families else None


def import_font_file(src: Path) -> str:
    """复制字体到 data/fonts/imported.* 并注册。"""
    if not src.is_file():
        raise FileNotFoundError(str(src))
    ext = src.suffix.lower()
    if ext not in (".ttf", ".otf", ".ttc"):
        raise ValueError("仅支持 .ttf / .otf / .ttc")
    dest = fonts_storage_dir() / f"{_IMPORTED_NAME}{ext}"
    for old in fonts_storage_dir().glob(f"{_IMPORTED_NAME}.*"):
        if old != dest:
            old.unlink(missing_ok=True)
    shutil.copy2(src, dest)
    fid = QFontDatabase.addApplicationFont(str(dest))
    if fid < 0:
        raise RuntimeError("字体注册失败")
    families = QFontDatabase.applicationFontFamilies(fid)
    if not families:
        raise RuntimeError("无法读取字体族名")
    return families[0]


def resolve_family(
    family: str,
    *,
    use_imported: bool = False,
    imported_family: str = "",
) -> str:
    if use_imported and imported_family:
        return imported_family
    f = (family or "").strip()
    if f and f in QFontDatabase.families():
        return f
    if f:
        return f
    return "Microsoft YaHei UI"


def make_font(
    family: str,
    size: int,
    *,
    use_imported: bool = False,
    imported_family: str = "",
) -> QFont:
    fam = resolve_family(
        family, use_imported=use_imported, imported_family=imported_family
    )
    return QFont(fam, size)
