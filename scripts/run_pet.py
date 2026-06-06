"""启动原生 Live2D 桌宠：先预拉 API 8765，再打开人物窗，大幅缩短等待时间。"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _setup_logging() -> None:
    from pnn.core.logging import setup_logging

    setup_logging()


def _prelaunch_api() -> None:
    """如果 API 8765 未运行，立即启动子进程（不等待就绪），让桌宠启动时已有 API 在预热。"""
    from pnn.core.api_health import is_api_alive, start_api_subprocess

    if is_api_alive(timeout=1.0):
        print("[pet] API 8765 已在线，跳过预启动", flush=True)
        return
    print("[pet] API 8765 未运行，后台启动中…", flush=True)
    try:
        start_api_subprocess()
    except Exception as exc:
        print(f"[pet] API 预启动失败（将在桌宠内重试）: {exc}", flush=True)


def main() -> None:
    _setup_logging()
    logging.getLogger("pet").info("优先加载人物模型与问候语音，API/TTS 在模型就绪后后台启动")

    _prelaunch_api()

    print("[pet] 正在打开人物窗（模型优先，其余服务稍后加载）…", flush=True)
    from pnn.pet.app import main as pet_main

    pet_main()


if __name__ == "__main__":
    main()
