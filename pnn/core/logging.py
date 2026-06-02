from __future__ import annotations

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """统一日志格式，输出到终端。"""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    for name in ("server", "pnn", "pnn.asr", "uvicorn", "uvicorn.error"):
        logging.getLogger(name).setLevel(level)
    for name in ("faster_whisper", "ctranslate2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("pnn.asr.stream").setLevel(logging.WARNING)
