from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from typing import Any

from pnn.core.config_cache import MtimeJsonConfigCache
from pnn.core.env import load_env
from pnn.core.paths import PROJECT_ROOT
from pnn.llm.paths import LLM_CONFIG_PATH, LOCAL_CONFIG_PATH

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
# MCP Agent（搜网页/改代码/截图任务）默认 Pro；日常闲聊用 model
DEFAULT_AGENT_MODEL = "deepseek-v4-pro"


@dataclass
class LlmConfig:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    agent_model: str = DEFAULT_AGENT_MODEL
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
    # 桌宠 NSFW：日常闲聊走本地 Qwen；MCP/Agent 仍用上方 base_url + agent_model
    nsfw_enabled: bool = False
    local_model_base_url: str = "http://127.0.0.1:8080"
    local_model: str = "qwen3.6"
    local_model_api_key: str = "local"
    # 本地 NSFW：精简上下文（无记忆、短标签说明、少历史），显著加速 35B prefill
    local_chat_lite: bool = True


_llm_config_cache = MtimeJsonConfigCache[LlmConfig]()
_llm_env_mtime_seen: float = -1.0


def _env_file_mtime() -> float:
    path = PROJECT_ROOT / ".env"
    try:
        return path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        return 0.0


def _is_local_llm_env_url(url: str) -> bool:
    from pnn.llm.routing import is_local_llm_url

    return is_local_llm_url(url)


def _env_overrides() -> dict[str, Any]:
    load_env(force=True)
    out: dict[str, Any] = {}
    key = (
        os.getenv("DEEPSEEK_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )
    from pnn.llm.routing import is_cloud_api_key

    if key and is_cloud_api_key(key):
        out["api_key"] = key
    base = (
        os.getenv("DEEPSEEK_BASE_URL", "").strip()
        or os.getenv("OPENAI_API_BASE", "").strip()
    )
    if base and not _is_local_llm_env_url(base):
        out["base_url"] = base.rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "").strip()
    if model and (not base or not _is_local_llm_env_url(base)):
        out["model"] = model
    agent_model = (
        os.getenv("AGENT_MODEL", "").strip()
        or os.getenv("DEEPSEEK_AGENT_MODEL", "").strip()
    )
    if agent_model:
        out["agent_model"] = agent_model
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
    local_base = os.getenv("LOCAL_LLM_BASE_URL", "").strip()
    if local_base:
        out["local_model_base_url"] = local_base.rstrip("/")
    local_model = os.getenv("LOCAL_LLM_MODEL", "").strip()
    if local_model:
        out["local_model"] = local_model
    local_key = os.getenv("LOCAL_LLM_API_KEY", "").strip()
    if local_key:
        out["local_model_api_key"] = local_key
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
    from pnn.llm.local_qwen import default_local_model_config

    for key, value in default_local_model_config().items():
        if hasattr(config, key):
            setattr(config, key, value)
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
        "agent_model",
        "vision_model",
        "vision_base_url",
        "vision_api_key",
        "local_model_base_url",
        "local_model",
        "local_model_api_key",
        "local_chat_lite",
    ):
        if key in env and hasattr(config, key):
            setattr(config, key, env[key])
    return config


def _load_llm_config_uncached() -> LlmConfig:
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


def load_llm_config() -> LlmConfig:
    global _llm_env_mtime_seen
    load_env(force=True)
    env_m = _env_file_mtime()
    if env_m != _llm_env_mtime_seen:
        _llm_config_cache.invalidate()
        _llm_env_mtime_seen = env_m
    return _llm_config_cache.get(LLM_CONFIG_PATH, _load_llm_config_uncached)


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
    _llm_config_cache.invalidate()


def mask_api_key(key: str) -> str:
    k = (key or "").strip()
    if len(k) <= 8:
        return "****" if k else ""
    return f"{k[:4]}…{k[-4:]}"
