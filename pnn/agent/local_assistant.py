"""本机助手 Agent 路由：由模型理解意图，不强依赖关键词。"""

from __future__ import annotations

from pnn.agent.routing import is_casual_chat_only


def any_local_assistant_chat_enabled() -> bool:
    try:
        from pnn.clipboard.service import clipboard_service
        from pnn.launch_apps.service import launch_apps_service
        from pnn.system_control.service import system_control_service

        return any(
            svc.chat_enabled()
            for svc in (launch_apps_service, system_control_service, clipboard_service)
        )
    except Exception:
        return False


def should_route_local_assistant_to_agent(text: str) -> bool:
    """本机助手已开启且非纯寒暄短句 → 走 Agent，由 LLM 决定是否调用 local__ 工具。"""
    raw = (text or "").strip()
    if not raw or is_casual_chat_only(raw):
        return False
    return any_local_assistant_chat_enabled()
