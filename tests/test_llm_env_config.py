"""LLM 配置从 .env 加载与 _ensure_configured 校验。"""

from __future__ import annotations

import pytest

from pnn.llm.config_store import load_llm_config, _llm_config_cache
from pnn.llm.routing import is_cloud_api_key
from pnn.llm.service import llm_service


def test_env_deepseek_key_loaded():
    _llm_config_cache.invalidate()
    cfg = load_llm_config()
    assert is_cloud_api_key(cfg.api_key), "DEEPSEEK_API_KEY 应从 .env 加载"
    assert cfg.base_url.startswith("https://")


def test_ensure_configured_daily_chat_with_env_key():
    _llm_config_cache.invalidate()
    llm_service.reload_from_disk()
    llm_service._ensure_configured(user_message="你好，睡了吗？")


def test_get_config_reports_configured():
    _llm_config_cache.invalidate()
    llm_service.reload_from_disk()
    cfg = llm_service.get_config()
    assert cfg.get("configured") is True
