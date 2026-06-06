"""日程 / 主动搭话运行期就绪检查。"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_boot_mono: float | None = None


def mark_pet_boot() -> None:
    """桌宠进程启动时调用一次。"""
    global _boot_mono
    _boot_mono = time.monotonic()


def boot_elapsed_seconds() -> float:
    if _boot_mono is None:
        return 0.0
    return max(0.0, time.monotonic() - _boot_mono)


def _llm_configured() -> bool:
    try:
        from pnn.core.env import load_env

        load_env()
        import os

        if (os.getenv("DEEPSEEK_API_KEY") or "").strip():
            return True
        from pnn.core.paths import CONFIG_DIR
        import json

        llm_path = CONFIG_DIR / "llm.json"
        if llm_path.is_file():
            data = json.loads(llm_path.read_text(encoding="utf-8"))
            return bool((data.get("api_key") or "").strip())
    except Exception:
        pass
    return False


def is_schedule_runtime_ready() -> bool:
    """LLM / API 基本可用（不保证 TTS 已预热）。"""
    try:
        from pnn.pet.api_guard import is_api_responsive

        if not is_api_responsive(timeout=2.5):
            return False
        return _llm_configured()
    except Exception:
        logger.debug("日程就绪检查失败")
        return False


def is_proactive_ready(*, controller_busy: bool = False) -> bool:
    """主动搭话前：API 稳定、已过启动静默期、桌宠未在问候/对话/播语音。"""
    if controller_busy:
        return False
    try:
        from pnn.pet.api_guard import is_api_recovering, is_api_responsive
        from pnn.pet.presence.config import load_presence_config

        cfg = load_presence_config()
        quiet = max(15, int(getattr(cfg, "presence_boot_quiet_seconds", 45)))
        if boot_elapsed_seconds() < quiet:
            return False
        if is_api_recovering(within_seconds=30.0):
            return False
        if not is_api_responsive(timeout=3.0):
            return False
        return _llm_configured()
    except Exception:
        logger.debug("主动搭话就绪检查失败")
        return False
