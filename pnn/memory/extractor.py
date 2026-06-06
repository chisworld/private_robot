from __future__ import annotations

import json
import logging
import re
from typing import Any

from pnn.llm.client import DeepSeekClient
from pnn.llm.config_store import load_llm_config
from pnn.memory.prompts import EXTRACT_SYSTEM, extract_user_block

logger = logging.getLogger(__name__)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    fence = re.search(r"\{[\s\S]*\}", raw)
    if fence:
        raw = fence.group(0)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def extract_memory_from_turn(
    user_message: str,
    assistant_reply: str,
    *,
    recent_history: str = "",
    related_memories: str = "",
    now_text: str = "",
    max_tokens: int = 500,
    user_label: str = "主人",
    assistant_label: str = "助手",
) -> dict[str, Any] | None:
    """调用 LLM 判断是否写入记忆。返回解析后的 dict 或 None。"""
    cfg = load_llm_config()
    if not cfg.api_key.strip():
        return None

    client = DeepSeekClient(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        timeout=60.0,
    )
    system = EXTRACT_SYSTEM
    if assistant_label.strip():
        system += (
            f"\n6. content 用一句简短中文；涉及助手自身信息时写「{assistant_label.strip()}的…」，"
            f"涉及助手时用「{assistant_label.strip()}」，不要写「桌宠」。"
            "禁止 save 内容为「表示不记得/没有记忆/想不起来」。"
        )
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": extract_user_block(
                user_message,
                assistant_reply,
                recent_history=recent_history,
                related_memories=related_memories,
                now_text=now_text,
                user_label=user_label,
                assistant_label=assistant_label,
            ),
        },
    ]
    try:
        result = client.chat(messages, temperature=0.2, max_tokens=max_tokens)
        parsed = _parse_json_object(result.get("content") or "")
        if parsed is None:
            logger.debug("记忆提取 JSON 解析失败: %s", (result.get("content") or "")[:200])
        return parsed
    except Exception as exc:
        logger.warning("记忆提取失败: %s", exc)
        return None
