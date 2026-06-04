"""OpenAI 兼容视觉 API：分析用户截图（DeepSeek 对话 API 本身不支持图片）。"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from pnn.core.env import load_env
from pnn.llm.config_store import load_llm_config

logger = logging.getLogger(__name__)

_DASHSCOPE_VL_DEFAULT = "qwen-vl-max"

# DashScope 识图可选模型（设置页与 .env DASHSCOPE_VL_MODEL）
DASHSCOPE_VL_MODELS: tuple[tuple[str, str], ...] = (
    ("qwen-vl-max", "效果最佳，复杂截图识别更准"),
    ("qwen-vl-plus", "速度与效果平衡"),
    ("qwen3-vl-plus", "Qwen3 视觉，长上下文"),
)

_VISION_PROMPT_DOWNLOAD = (
    "用户附了一张截图，希望在指定网站找到并下载「截图中的这一张图」（不是页面全部图片）。\n"
    "请描述图中目标图片的独特特征，便于在网站搜索结果里唯一定位它：\n"
    "• 人物/角色名、作品名、姿势、服装、表情\n"
    "• 画面构图（特写/半身/全身）、背景、主色调\n"
    "• 可见文字、Logo、水印\n"
    "• 与相似图的区别点（若截图来自画廊，说明是哪一张）\n"
    "用简洁中文条目列出，便于浏览器自动化只匹配并下载这一张。"
)

_VISION_PROMPT_PREVIEW = (
    "用户附了一张屏幕截图。请用简洁中文描述你看到了什么，便于主人确认你是否识别正确：\n"
    "• 主要界面、应用或网页；可见标题与文字\n"
    "• 若是图片/角色/游戏画面：人物、作品名、服装、姿势、主色调\n"
    "• 3～6 条短句，每条一行，不要冗长、不要猜测看不见的内容"
)

# 兼容旧名
_VISION_PROMPT = _VISION_PROMPT_DOWNLOAD


def _normalize_vision_base_url(base: str) -> str:
    """DashScope OpenAI 兼容端点为 /compatible-mode/v1，非 /api/v1。"""
    b = (base or "").strip().rstrip("/")
    if not b:
        return b
    if "dashscope.aliyuncs.com" in b and b.endswith("/api/v1"):
        return b[: -len("/api/v1")] + "/compatible-mode/v1"
    return b


def _vision_endpoint(base: str) -> str:
    b = _normalize_vision_base_url(base)
    if b.endswith("/v1"):
        return f"{b}/chat/completions"
    return f"{b}/v1/chat/completions"


def resolve_vision_settings() -> tuple[str, str, str]:
    """返回 (api_key, base_url, model)。"""
    load_env()
    cfg = load_llm_config()
    key = (
        os.getenv("VISION_API_KEY", "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
        or (cfg.vision_api_key or "").strip()
        or cfg.api_key.strip()
    )
    base = (
        os.getenv("VISION_BASE_URL", "").strip()
        or os.getenv("DASHSCOPE_BASE_URL", "").strip()
        or (cfg.vision_base_url or "").strip()
        or cfg.base_url.strip()
        or "https://api.deepseek.com"
    ).rstrip("/")
    base = _normalize_vision_base_url(base)

    model = (
        os.getenv("VISION_MODEL", "").strip()
        or os.getenv("DASHSCOPE_VL_MODEL", "").strip()
        or os.getenv("DASHSCOPE_VISION_MODEL", "").strip()
        or (cfg.vision_model or "").strip()
    )
    if not model and (
        os.getenv("DASHSCOPE_API_KEY", "").strip()
        or "dashscope.aliyuncs.com" in base
    ):
        model = _DASHSCOPE_VL_DEFAULT
    return key, base, model


def vision_configured() -> bool:
    key, _, model = resolve_vision_settings()
    return bool(key and model)


def describe_image(
    image_base64: str,
    mime: str = "image/png",
    *,
    user_hint: str = "",
    purpose: str = "download",
    cached_analysis: str = "",
) -> str:
    cached = (cached_analysis or "").strip()
    if cached:
        return cached

    key, base, model = resolve_vision_settings()
    if not key:
        raise ValueError("未配置视觉 API Key（可与 LLM 共用，或设置 VISION_API_KEY）")
    if not model:
        raise ValueError(
            "未配置视觉模型。请在设置 → LLM 填写「视觉模型」，"
            "或在 .env 设置 DASHSCOPE_VL_MODEL（如 qwen-vl-max）或 VISION_MODEL。"
        )

    b64 = (image_base64 or "").strip()
    if not b64:
        raise ValueError("图片数据为空")

    hint = (user_hint or "").strip()
    purpose_key = (purpose or "download").strip().lower()
    prompt = _VISION_PROMPT_PREVIEW if purpose_key == "preview" else _VISION_PROMPT_DOWNLOAD
    if hint:
        prompt += f"\n\n用户附言：{hint}"

    endpoint = _vision_endpoint(base)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 1024,
        "temperature": 0.2,
    }
    try:
        res = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90.0,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"视觉 API 请求失败: {exc}") from exc

    if not res.ok:
        detail = res.text[:500]
        try:
            err = res.json().get("error") or {}
            if isinstance(err, dict):
                detail = err.get("message") or detail
        except Exception:
            pass
        raise RuntimeError(f"视觉 API 错误 ({res.status_code}): {detail}")

    data = res.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("视觉 API 未返回内容")
    msg = choices[0].get("message") or {}
    content = (msg.get("content") or "").strip()
    if not content:
        raise RuntimeError("视觉 API 返回空描述")
    return content


def describe_image_preview(
    image_base64: str,
    mime: str = "image/png",
    *,
    user_hint: str = "",
) -> str:
    """附截图瞬间：通用识图描述（气泡展示用）。"""
    return describe_image(
        image_base64,
        mime,
        user_hint=user_hint,
        purpose="preview",
    )

