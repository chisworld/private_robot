"""「打开 XX」类指令：匹配白名单后直接启动，不依赖 LLM 调工具。"""

from __future__ import annotations

import logging
import re

from pnn.launch_apps.routing import needs_launch_app_task

logger = logging.getLogger(__name__)

_OPEN_TARGET_RE = re.compile(
    r"(?:打开|启动|运行|开一下|开下|开开|开启|launch|open|start)\s*"
    r"([^\s，。！!？?、,；;]+)",
    re.IGNORECASE,
)


def try_direct_launch_app(user_message: str) -> str | None:
    from pnn.launch_apps.service import launch_apps_service

    text = (user_message or "").strip()
    if not text or not needs_launch_app_task(text):
        return None
    launch_apps_service.reload_config()
    if not launch_apps_service.chat_enabled():
        return None

    entry = launch_apps_service.find_app_in_text(text)
    if entry is None:
        m = _OPEN_TARGET_RE.search(text)
        if m:
            entry = launch_apps_service.resolve_app(m.group(1))
    if entry is None:
        return None

    try:
        result = launch_apps_service.launch_entry(entry)
    except FileNotFoundError as exc:
        result = str(exc)
    except Exception as exc:
        result = f"启动失败: {exc}"
    if not result or result.startswith("打开程序失败") or "未找到" in result or "不存在" in result:
        logger.warning("[launch_apps] 直接启动失败: %s -> %s", text, result)
        return None
    logger.info("[launch_apps] 直接启动成功: %s -> %s", text, result)
    return result
