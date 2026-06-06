"""桌宠侧 API 健康守护：检测 8765 僵死并自动重启。"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_recover_lock = threading.Lock()
_last_recover_at = 0.0


def is_api_responsive(*, timeout: float = 2.5) -> bool:
    from pnn.core.api_health import is_api_ready_for_pet

    return is_api_ready_for_pet(timeout=timeout)


def is_api_recovering(*, within_seconds: float = 30.0) -> bool:
    """API 刚自动重启/拉起后的短暂冷静期，避免主动搭话撞上未就绪。"""
    if _last_recover_at <= 0:
        return False
    return (time.monotonic() - _last_recover_at) < max(0.0, within_seconds)


def recover_api_if_stuck(
    *,
    reason: str = "",
    cooldown: float = 40.0,
    restart_timeout: float = 60.0,
) -> bool:
    """health/对话不可用时重启 API；cooldown 内避免连续重启。"""
    global _last_recover_at
    with _recover_lock:
        now = time.monotonic()
        if now - _last_recover_at < cooldown and is_api_responsive(timeout=2.0):
            return True
        if is_api_responsive(timeout=2.5):
            return True

        from pnn.core.api_health import (
            ensure_api_for_pet,
            is_api_alive,
            restart_api,
        )

        tag = reason or "无响应"
        if is_api_alive(timeout=1.5):
            logger.warning("API(8765) %s，正在自动重启…", tag)
            ok = restart_api(timeout=restart_timeout)
        else:
            logger.warning("API(8765) 未运行 (%s)，正在拉起…", tag)
            ok = ensure_api_for_pet(timeout=restart_timeout)
        _last_recover_at = time.monotonic()
        if ok:
            logger.info("API(8765) 已恢复")
        else:
            logger.error("API(8765) 自动恢复失败，请查看 data\\logs\\api_boot.log")
        return ok


def ensure_api_before_chat() -> bool:
    """发 LLM 请求前调用；无响应则尝试恢复。"""
    if is_api_responsive(timeout=3.0):
        return True
    return recover_api_if_stuck(reason="对话前检查", cooldown=20.0)
