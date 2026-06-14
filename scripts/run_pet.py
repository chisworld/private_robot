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
    """启动或重启 API 8765，确保加载最新代码与 .env。"""
    from pnn.core.api_health import ensure_fresh_api_for_pet

    print("[pet] 检查 API 8765（必要时重启以加载最新 .env）…", flush=True)
    try:
        ok = ensure_fresh_api_for_pet(timeout=45.0)
        if ok:
            print("[pet] API 8765 已就绪", flush=True)
        else:
            print("[pet] API 8765 未完全就绪（桌宠内将继续重试）", flush=True)
    except Exception as exc:
        print(f"[pet] API 预启动失败（将在桌宠内重试）: {exc}", flush=True)


def _prelaunch_local_qwen() -> None:
    """若已安装 Qwen 整合包，后台启动 llama-server（无需单独运行 start_qwen_local.bat）。"""
    from pnn.llm.local_qwen_server import prelaunch_local_qwen_for_pet

    prelaunch_local_qwen_for_pet()


def main() -> None:
    _setup_logging()
    from pnn.pet.console_log import configure_pet_stdio_utf8

    configure_pet_stdio_utf8()
    logging.getLogger("pet").info("优先加载人物模型与问候语音，API/TTS 在模型就绪后后台启动")

    _prelaunch_api()
    _prelaunch_local_qwen()

    from pnn.pet.console_log import log_llm_startup_banner

    log_llm_startup_banner()

    print("[pet] 正在打开人物窗（模型优先，其余服务稍后加载）…", flush=True)
    from pnn.pet.app import main as pet_main

    pet_main()


if __name__ == "__main__":
    main()
