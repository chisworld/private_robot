"""启动原生 Live2D 桌宠：窗口先显示，API 8765 在后台拉起（不打开网页）。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _setup_logging() -> None:
    from pnn.core.logging import setup_logging

    setup_logging()


def main() -> None:
    _setup_logging()
    logging.getLogger("pet").info("优先加载人物模型与问候语音，API/TTS 在模型就绪后后台启动")
    print("[pet] 正在打开人物窗（模型优先，其余服务稍后加载）…", flush=True)
    from pnn.pet.app import main as pet_main

    pet_main()


if __name__ == "__main__":
    main()
