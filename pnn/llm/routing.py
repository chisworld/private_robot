"""日常闲聊 vs MCP/Agent 的 LLM 路由。"""

from __future__ import annotations

from pnn.agent.routing import needs_mcp_agent
from pnn.llm.config_store import LlmConfig

# NSFW 开启时禁用的 presence 主动搭话（日程/番茄钟提醒不在此列）
NSFW_BLOCKED_PRESENCE_KINDS = frozenset(
    {
        "idle",
        "afk",
        "session_resume",
        "writing_nudge",
        "return_focus",
        "absence_return",
        "time_greeting",
        "holiday_greeting",
        "window_greet",
    }
)


def is_local_llm_url(base_url: str) -> bool:
    b = (base_url or "").strip().lower().rstrip("/")
    return b.startswith("http://127.0.0.1") or b.startswith("http://localhost")


def is_cloud_api_key(key: str) -> bool:
    k = (key or "").strip()
    return bool(k) and k.lower() not in ("local", "none", "sk-your-key-here")


def _blocked_for_local_chat(
    user_message: str,
    *,
    use_agent: bool = False,
    image_base64: str | None = None,
    image_analysis: str | None = None,
) -> bool:
    if use_agent:
        return True
    if (image_base64 or "").strip() or (image_analysis or "").strip():
        return True
    return needs_mcp_agent(
        user_message,
        image_base64=image_base64,
        image_analysis=image_analysis,
    )


def local_llm_ready(cfg: LlmConfig) -> bool:
    from pnn.llm.local_qwen import local_llm_health

    ok, _ = local_llm_health(cfg.local_model_base_url)
    return ok


def nsfw_blocks_presence_proactive(kind: str) -> bool:
    """NSFW 模式下跳过空闲/问候类主动搭话（用户主动发消息不受影响）。"""
    from pnn.llm.config_store import load_llm_config

    if not load_llm_config().nsfw_enabled:
        return False
    k = (kind or "").strip().lower()
    if not k:
        return True
    return k in NSFW_BLOCKED_PRESENCE_KINDS


def use_local_nsfw_chat(
    cfg: LlmConfig,
    user_message: str,
    *,
    use_agent: bool = False,
    image_base64: str | None = None,
    image_analysis: str | None = None,
) -> bool:
    """NSFW 开启且为日常闲聊（非 MCP/截图任务）时走本地 Qwen。"""
    if not cfg.nsfw_enabled:
        return False
    if _blocked_for_local_chat(
        user_message,
        use_agent=use_agent,
        image_base64=image_base64,
        image_analysis=image_analysis,
    ):
        return False
    return True


def should_use_local_chat(
    cfg: LlmConfig,
    user_message: str,
    *,
    use_agent: bool = False,
    image_base64: str | None = None,
    image_analysis: str | None = None,
) -> bool:
    """日常闲聊是否走本地 Qwen（NSFW 开启，或无云端 Key 且本地服务已就绪）。"""
    if _blocked_for_local_chat(
        user_message,
        use_agent=use_agent,
        image_base64=image_base64,
        image_analysis=image_analysis,
    ):
        return False
    if use_local_nsfw_chat(
        cfg,
        user_message,
        use_agent=use_agent,
        image_base64=image_base64,
        image_analysis=image_analysis,
    ):
        return True
    if is_cloud_api_key(cfg.api_key):
        return False
    return local_llm_ready(cfg)


def describe_chat_route(
    cfg: LlmConfig,
    user_message: str,
    *,
    use_agent: bool = False,
    image_base64: str | None = None,
    image_analysis: str | None = None,
) -> dict[str, str | bool]:
    """返回当前消息将使用的 LLM 路由（供终端提示与 SSE）。"""
    if use_agent:
        model = (cfg.agent_model or "deepseek-v4-pro").strip() or "deepseek-v4-pro"
        return {
            "route": "agent",
            "label": "DeepSeek Agent（MCP）",
            "model": model,
            "base_url": (cfg.base_url or "").strip(),
            "nsfw_enabled": bool(cfg.nsfw_enabled),
        }
    if should_use_local_chat(
        cfg,
        user_message,
        use_agent=False,
        image_base64=image_base64,
        image_analysis=image_analysis,
    ):
        from pnn.llm.local_qwen import (
            local_chat_lite_enabled,
            local_chat_max_history,
            local_chat_max_tokens,
        )

        base = (cfg.local_model_base_url or "http://127.0.0.1:8080").strip().rstrip("/")
        model = (cfg.local_model or "qwen3.6").strip() or "qwen3.6"
        lite = local_chat_lite_enabled(cfg.local_chat_lite)
        return {
            "route": "local_qwen",
            "label": "本地 Qwen（NSFW）",
            "model": model,
            "base_url": base,
            "nsfw_enabled": True,
            "local_chat_lite": lite,
            "local_history_cap": local_chat_max_history(cfg.max_history_messages, lite=lite),
            "local_max_tokens": local_chat_max_tokens(lite=lite),
        }
    model = (cfg.model or "deepseek-chat").strip() or "deepseek-chat"
    return {
        "route": "deepseek",
        "label": "DeepSeek 云端",
        "model": model,
        "base_url": (cfg.base_url or "").strip(),
        "nsfw_enabled": bool(cfg.nsfw_enabled),
    }


def format_route_terminal(info: dict[str, str | bool]) -> str:
    route = str(info.get("route") or "")
    model = str(info.get("model") or "")
    base = str(info.get("base_url") or "")
    label = str(info.get("label") or route)
    if route == "local_qwen":
        return f"{label} → {model} @ {base}"
    if route == "agent":
        nsfw = info.get("nsfw_enabled")
        note = "（MCP/工具任务，NSFW 不覆盖）" if nsfw else ""
        return f"{label} → {model}{note}"
    return f"{label} → {model} ({base})"
