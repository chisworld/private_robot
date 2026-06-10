from __future__ import annotations

import logging

from pnn.llm.client import DeepSeekClient
from pnn.llm.config_store import load_llm_config

logger = logging.getLogger(__name__)

MERGE_SYSTEM = """你是记忆库管理员。将「旧记忆」与「新信息」合并为一条简洁的中文事实记忆。
规则：
1. 若新信息否定或更新旧信息（如戒可乐、换喜好），以新信息为准，不要保留矛盾。
2. 若新信息是补充细节，合并到一条里。
3. 只输出合并后的一条记忆正文，不要解释、不要 JSON、不要引号。"""


def merge_memory_with_llm(old_content: str, new_content: str) -> str | None:
    old_content = (old_content or "").strip()
    new_content = (new_content or "").strip()
    if not new_content:
        return None
    if not old_content:
        return new_content

    cfg = load_llm_config()
    if not cfg.api_key.strip():
        return new_content

    client = DeepSeekClient(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        timeout=45.0,
    )
    user = f"旧记忆：{old_content[:1200]}\n新信息：{new_content[:1200]}"
    messages = [
        {"role": "system", "content": MERGE_SYSTEM},
        {"role": "user", "content": user},
    ]
    for attempt in range(2):
        try:
            result = client.chat_completion(
                messages,
                temperature=0.2,
                max_tokens=256,
                thinking_enabled=False,
            )
            message = result.get("message") or {}
            merged = (message.get("content") or "").strip()
            if merged and len(merged) >= 4:
                return merged
            if attempt == 0:
                logger.debug("记忆合并 LLM 空回复，重试一次")
                continue
            logger.debug("记忆合并 LLM 无有效正文，保留新信息")
        except Exception as exc:
            if attempt == 0:
                logger.debug("记忆合并 LLM 失败，重试一次: %s", exc)
                continue
            logger.warning("记忆合并 LLM 失败: %s", exc)
    return new_content
