"""可确定解析的系统操控：直接执行，不依赖 LLM 是否调工具。"""

from __future__ import annotations

import logging

from pnn.system_control.config_store import SET_BRIGHTNESS_TOOL, SET_VOLUME_TOOL
from pnn.system_control.routing import parse_brightness_adjustment, parse_volume_adjustment

logger = logging.getLogger(__name__)


def try_direct_system_control(user_message: str) -> str | None:
    """解析到明确参数时立即调用本机工具。成功返回结果文案，否则 None。"""
    from pnn.system_control.service import system_control_service

    if not system_control_service.chat_enabled():
        return None

    text = (user_message or "").strip()
    if not text:
        return None

    tool: str | None = None
    args: dict[str, int] = {}

    vol = parse_volume_adjustment(text)
    if vol == "mute":
        tool, args = SET_VOLUME_TOOL, {"percent": 0}
    elif vol == "unmute":
        tool, args = SET_VOLUME_TOOL, {"percent": 30}
    elif isinstance(vol, dict):
        if "percent" in vol:
            tool, args = SET_VOLUME_TOOL, {"percent": int(vol["percent"])}
        elif "delta" in vol:
            tool, args = SET_VOLUME_TOOL, {"delta": int(vol["delta"])}

    if tool is None:
        adj = parse_brightness_adjustment(text)
        if isinstance(adj, dict):
            if "percent" in adj:
                tool, args = SET_BRIGHTNESS_TOOL, {"percent": int(adj["percent"])}
            elif "delta" in adj:
                tool, args = SET_BRIGHTNESS_TOOL, {"delta": int(adj["delta"])}

    if tool is None:
        return None

    try:
        result = system_control_service.call_tool(tool, args)
    except Exception as exc:
        logger.warning("[system_control] 直接执行失败: %s %s -> %s", tool, args, exc)
        return None

    if not result or result.startswith(("设置音量失败", "调节亮度失败", "缺少参数", "未知系统工具")):
        logger.warning("[system_control] 直接执行未成功: %s %s -> %s", tool, args, result)
        return None

    logger.info("[system_control] 直接执行成功: %s %s -> %s", tool, args, result)
    return result
