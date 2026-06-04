from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from typing import Any

from pnn.core.env import load_env
from pnn.llm.paths import LLM_CONFIG_PATH, LOCAL_CONFIG_PATH

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@dataclass
class LlmConfig:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    # 输出/对话规则（llm.json）；人物设定见 data/config/{active_character}.json
    system_prompt: str = ""
    active_character: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    max_history_messages: int = 20
    # DeepSeek V4 思考模式（reasoning_content + content）
    thinking_enabled: bool = False
    reasoning_effort: str = "high"  # high | max
    # 识图（OpenAI 兼容多模态；DeepSeek 对话 API 不支持图片，需单独模型）
    vision_model: str = ""
    vision_base_url: str = ""
    vision_api_key: str = ""


def _env_overrides() -> dict[str, Any]:
    load_env()
    out: dict[str, Any] = {}
    key = (
        os.getenv("DEEPSEEK_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )
    if key:
        out["api_key"] = key
    base = (
        os.getenv("DEEPSEEK_BASE_URL", "").strip()
        or os.getenv("OPENAI_API_BASE", "").strip()
    )
    if base:
        out["base_url"] = base.rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "").strip()
    if model:
        out["model"] = model
    vision_key = os.getenv("VISION_API_KEY", "").strip()
    if vision_key:
        out["vision_api_key"] = vision_key
    dash_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if dash_key and "vision_api_key" not in out:
        out["vision_api_key"] = dash_key
    vision_base = (
        os.getenv("VISION_BASE_URL", "").strip()
        or os.getenv("DASHSCOPE_BASE_URL", "").strip()
    )
    if vision_base:
        out["vision_base_url"] = vision_base.rstrip("/")
    vision_model = (
        os.getenv("VISION_MODEL", "").strip()
        or os.getenv("DASHSCOPE_VL_MODEL", "").strip()
        or os.getenv("DASHSCOPE_VISION_MODEL", "").strip()
    )
    if vision_model:
        out["vision_model"] = vision_model
    return out


def _local_config_overrides() -> dict[str, Any]:
    if not LOCAL_CONFIG_PATH.is_file():
        return {}
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("pnn_local_config", LOCAL_CONFIG_PATH)
        if spec is None or spec.loader is None:
            return {}
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        logger.warning("读取 local_config.py 失败: %s", exc)
        return {}

    out: dict[str, Any] = {}
    key = getattr(mod, "DEEPSEEK_API_KEY", "") or getattr(mod, "OPENAI_API_KEY", "")
    if str(key).strip():
        out["api_key"] = str(key).strip()
    base = getattr(mod, "OPENAI_API_BASE", "") or getattr(mod, "DEEPSEEK_BASE_URL", "")
    if str(base).strip():
        out["base_url"] = str(base).strip().rstrip("/")
    model = getattr(mod, "DEEPSEEK_MODEL", "")
    if str(model).strip():
        out["model"] = str(model).strip()
    return out


def build_default_config() -> LlmConfig:
    config = LlmConfig()
    for key, value in _local_config_overrides().items():
        if hasattr(config, key):
            setattr(config, key, value)
    for key, value in _env_overrides().items():
        if hasattr(config, key):
            setattr(config, key, value)
    return config


def _apply_optional_overrides(config: LlmConfig) -> LlmConfig:
    """local_config / .env 补齐；.env 中的密钥与 base_url 优先于 llm.json。"""
    for key, value in _local_config_overrides().items():
        if key == "system_prompt":
            continue
        if hasattr(config, key) and not getattr(config, key):
            setattr(config, key, value)
    env = _env_overrides()
    for key in (
        "api_key",
        "base_url",
        "model",
        "vision_model",
        "vision_base_url",
        "vision_api_key",
    ):
        if key in env and hasattr(config, key):
            setattr(config, key, env[key])
    return config


def load_llm_config() -> LlmConfig:
    if not LLM_CONFIG_PATH.is_file():
        config = build_default_config()
        save_llm_config(config)
        return config

    try:
        raw = json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 LLM 配置失败，将使用默认值: %s", exc)
        config = build_default_config()
        save_llm_config(config)
        return config

    allowed = {f.name for f in fields(LlmConfig)}
    kwargs = {k: v for k, v in raw.items() if k in allowed}
    try:
        config = LlmConfig(**{k: kwargs.get(k, getattr(LlmConfig(), k)) for k in allowed})
    except TypeError as exc:
        logger.warning("LLM 配置字段异常，将重置为默认值: %s", exc)
        config = build_default_config()
        save_llm_config(config)
        return config

    if config.max_tokens < 256:
        config.max_tokens = 1024
        save_llm_config(config)

    if config.reasoning_effort not in ("high", "max"):
        config.reasoning_effort = "high"

    return _apply_optional_overrides(config)


def save_llm_config(config: LlmConfig, *, keep_api_key: bool = False) -> None:
    LLM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(config)
    env_key = _env_overrides().get("api_key", "")
    if not keep_api_key and env_key and payload.get("api_key", "").strip() == env_key:
        payload["api_key"] = ""
    LLM_CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def mask_api_key(key: str) -> str:
    k = (key or "").strip()
    if len(k) <= 8:
        return "****" if k else ""
    return f"{k[:4]}…{k[-4:]}"
