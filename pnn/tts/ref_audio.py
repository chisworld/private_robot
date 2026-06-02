from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from pnn.tts.paths import TTS_REFERENCE_DIR

logger = logging.getLogger(__name__)


def _slugify(label: str, fallback: str = "emotion") -> str:
    slug = re.sub(r"[^\w\-]+", "_", label.strip(), flags=re.UNICODE).strip("_").lower()
    return slug or fallback


def mirror_reference_audio(ref_path: str, *, dest_name: str = "character_ref.wav") -> str:
    """将外部参考音频复制到项目目录，避免路径空格/编码问题。"""
    src = Path(ref_path)
    if not src.is_file():
        return ref_path
    try:
        if src.resolve().is_relative_to(TTS_REFERENCE_DIR.resolve()):
            return str(src.resolve())
    except ValueError:
        pass

    dest = TTS_REFERENCE_DIR / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file() or src.stat().st_mtime > dest.stat().st_mtime:
        shutil.copy2(src, dest)
        logger.info("已镜像参考音频: %s", dest)
    return str(dest.resolve())


def mirror_emotion_reference(preset_id: str, ref_path: str) -> str:
    safe_id = _slugify(preset_id, "emotion")
    return mirror_reference_audio(ref_path, dest_name=f"emotions/{safe_id}.wav")
