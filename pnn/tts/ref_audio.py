from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from pnn.tts.character_layout import (
    LEGACY_REFERENCE_DIR,
    active_character_id,
    character_emotions_dir,
    character_reference_wav,
)

logger = logging.getLogger(__name__)


def _slugify(label: str, fallback: str = "emotion") -> str:
    slug = re.sub(r"[^\w\-]+", "_", label.strip(), flags=re.UNICODE).strip("_").lower()
    return slug or fallback


def mirror_reference_audio(
    ref_path: str,
    *,
    char_id: str | None = None,
    dest_name: str = "reference.wav",
) -> str:
    """将参考音频复制到 data/tts/{角色ID}/reference.wav。"""
    src = Path(ref_path)
    if not src.is_file():
        return ref_path
    cid = char_id or active_character_id()
    dest = character_reference_wav(cid)
    if dest_name != "reference.wav":
        dest = dest.parent / dest_name
    try:
        if src.resolve() == dest.resolve():
            return str(dest.resolve())
    except ValueError:
        pass
    try:
        if src.resolve().is_relative_to(character_reference_wav(cid).parent.resolve()):
            return str(src.resolve())
    except (ValueError, OSError):
        pass
    if LEGACY_REFERENCE_DIR in src.parents and src.name == "character_ref.wav":
        pass

    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file() or src.stat().st_mtime > dest.stat().st_mtime:
        shutil.copy2(src, dest)
        logger.info("已镜像参考音频 [%s]: %s", cid, dest)
    return str(dest.resolve())


def mirror_emotion_reference(
    preset_id: str,
    ref_path: str,
    *,
    char_id: str | None = None,
) -> str:
    safe_id = _slugify(preset_id, "emotion")
    dest = character_emotions_dir(char_id) / f"{safe_id}.wav"
    src = Path(ref_path)
    if not src.is_file():
        return ref_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file() or src.stat().st_mtime > dest.stat().st_mtime:
        shutil.copy2(src, dest)
        logger.info("已镜像情绪参考音 [%s]: %s", char_id or active_character_id(), dest)
    return str(dest.resolve())
