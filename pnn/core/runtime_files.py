"""运行期临时文件：统一落在项目 cache/ 下，不使用系统 %TEMP%。"""

from __future__ import annotations

import uuid
from pathlib import Path

from pnn.core.paths import CACHE_DIR, PROJECT_ROOT

# cache/tmp/{asr,tts,playback,...}
RUNTIME_TMP_DIR = CACHE_DIR / "tmp"


def ensure_runtime_dir(subdir: str = "") -> Path:
    root = RUNTIME_TMP_DIR / subdir if subdir else RUNTIME_TMP_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def alloc_runtime_path(suffix: str = ".wav", *, subdir: str = "misc") -> Path:
    """在 cache/tmp/<subdir>/ 下生成唯一文件路径（不自动创建文件）。"""
    parent = ensure_runtime_dir(subdir)
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    return parent / f"{uuid.uuid4().hex}{ext}"


def is_under_project(path: str | Path) -> bool:
    try:
        Path(path).expanduser().resolve().relative_to(PROJECT_ROOT.resolve())
        return True
    except (ValueError, OSError):
        return False
