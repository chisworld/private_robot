from __future__ import annotations

import logging
from pathlib import Path

from pnn.core.paths import CACHE_DIR

logger = logging.getLogger(__name__)

AUDIO_CACHE_DIR = CACHE_DIR / "audio"
MAX_AUDIO_CACHE_FILES = 20


def prune_audio_cache(
    cache_dir: Path | None = None,
    *,
    max_files: int = MAX_AUDIO_CACHE_FILES,
) -> int:
    """删除最旧的 wav，使目录内文件数不超过 max_files。返回删除数量。"""
    root = Path(cache_dir or AUDIO_CACHE_DIR)
    if not root.is_dir():
        return 0
    files = sorted(
        (p for p in root.glob("*.wav") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    excess = len(files) - max(0, max_files)
    if excess <= 0:
        return 0
    removed = 0
    for path in files[:excess]:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            logger.debug("删除缓存音频失败 %s: %s", path, exc)
    if removed:
        logger.info("已清理 %s 个旧 TTS 缓存（保留最近 %s 个）", removed, max_files)
    return removed


def ensure_audio_cache_dir() -> Path:
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    prune_audio_cache(AUDIO_CACHE_DIR)
    return AUDIO_CACHE_DIR
