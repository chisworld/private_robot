"""设置页本地配置读取（与 8765 同源 JSON；API 繁忙/超时时 fallback）。"""

from __future__ import annotations

from typing import Any


def load_chat_config_local() -> dict[str, Any]:
    from pnn.llm.service import llm_service
    from server.routes.chat import STREAM_SSE_VERSION

    cfg = llm_service.get_config()
    cfg["stream_sse_version"] = STREAM_SSE_VERSION
    cfg["agent_enabled"] = llm_service.agent_enabled_for_config()
    return cfg


def list_character_packs_local() -> list[dict[str, str]]:
    from pnn.characters.service import character_pack_service

    return character_pack_service.list_packs()


def list_characters_local() -> list[dict[str, str]]:
    from pnn.llm.service import llm_service

    return llm_service.list_characters()


def load_memory_config_local() -> dict[str, Any]:
    from pnn.memory.service import memory_service

    return memory_service.get_config()


def list_memories_local(limit: int = 80) -> list[dict[str, Any]]:
    from pnn.memory.service import memory_service

    return memory_service.list_memories(limit)


def list_dialogue_history_local(limit: int = 800, *, days: int = 60) -> list[dict[str, Any]]:
    from pnn.memory.service import memory_service

    return memory_service.list_dialogue_history(limit, days=days)


def memory_stats_local() -> dict[str, Any]:
    from pnn.memory.service import memory_service

    return memory_service.memory_stats()


def load_translate_config_local() -> dict[str, Any]:
    from pnn.translate.service import translate_service

    return translate_service.get_config()


def load_tts_config_local() -> dict[str, Any]:
    from pnn.tts.service import tts_service

    return tts_service.get_config(probe_server=False)


def load_asr_config_local() -> dict[str, Any]:
    from pnn.asr.service import asr_service

    return asr_service.get_config()


def load_mcp_config_local() -> dict[str, Any]:
    from pnn.mcp.service import mcp_service

    return mcp_service.get_config()


def load_mcp_status_local() -> dict[str, Any]:
    from pnn.mcp.service import mcp_service

    cfg = mcp_service.get_config()
    return {
        **cfg,
        "ready": mcp_service.is_ready(),
        "agent_ready": mcp_service.chat_enabled(),
    }


def load_launch_apps_config_local() -> dict[str, Any]:
    from pnn.launch_apps.service import launch_apps_service

    return launch_apps_service.get_config()


def load_settings_payload_local() -> dict[str, Any]:
    """API 不可达时整页设置数据（与 _RemoteConfigLoader 结构一致）。"""
    packs = list_character_packs_local()
    if not packs:
        packs = list_characters_local()
    mcp_cfg = load_mcp_config_local()
    mcp_st = load_mcp_status_local()
    return {
        "chat": load_chat_config_local(),
        "characters": packs,
        "packs": packs,
        "memory": load_memory_config_local(),
        "memories": list_memories_local(80),
        "translate": load_translate_config_local(),
        "tts": load_tts_config_local(),
        "asr": load_asr_config_local(),
        "mcp": {**mcp_cfg, **mcp_st},
        "launch_apps": load_launch_apps_config_local(),
        "_load_warnings": ["API 无响应，已使用本地 JSON 配置"],
    }
