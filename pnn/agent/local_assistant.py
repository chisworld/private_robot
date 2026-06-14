"""本机助手 Agent 路由：仅当消息像系统操控/启动程序/剪贴板任务时才走 Agent。"""

from __future__ import annotations

import re

from pnn.agent.routing import is_casual_chat_only

# 桌宠助手工具意图（闲聊/角色扮演不应匹配）
_LOCAL_ASSISTANT_TASK_RE = re.compile(
    r"(?:"
    r"打开|启动|运行|开一下|点开|关掉|关闭"
    r"|音量|声音|静音|大声|小声|刺耳|刺眼|太亮|太暗|亮一点|暗一点|亮度|屏幕|显示器|媒体"
    r"|剪贴板|复制的内容|粘贴的"
    r"|关机|定时关机|休眠|锁屏"
    r"|(?:qq|QQ).{0,8}(?:音乐|播放)|播放|暂停|下一首|上一首|切歌"
    r"|回收站|清空"
    r")",
    re.IGNORECASE,
)


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


def looks_like_local_assistant_task(text: str) -> bool:
    """True = 可能需 local__ 工具（音量/启动程序/剪贴板等）。"""
    raw = (text or "").strip()
    if not raw:
        return False
    return bool(_LOCAL_ASSISTANT_TASK_RE.search(raw))


def should_route_local_assistant_to_agent(text: str) -> bool:
    """本机助手已开启且消息像操控任务 → 走 Agent；闲聊/角色扮演走普通对话。"""
    raw = (text or "").strip()
    if not raw or is_casual_chat_only(raw):
        return False
    try:
        from pnn.llm.config_store import load_llm_config
        from pnn.llm.routing import use_local_nsfw_chat

        cfg = load_llm_config()
        if use_local_nsfw_chat(cfg, raw, use_agent=False):
            return False
    except Exception:
        pass
    if not looks_like_local_assistant_task(raw):
        return False
    return any_local_assistant_chat_enabled()
