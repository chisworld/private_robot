from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import requests

logger = logging.getLogger(__name__)


def model_supports_thinking(model: str) -> bool:
    """DeepSeek V4 Pro / reasoner 支持 thinking；V4 Flash 不支持。"""
    mid = (model or "").strip().lower()
    if not mid:
        return False
    if "flash" in mid:
        return False
    if "reasoner" in mid:
        return True
    return mid == "deepseek-v4-pro" or mid.endswith("-v4-pro")


class DeepSeekClient:
    """DeepSeek OpenAI 兼容 Chat Completions API。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        *,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "https://api.deepseek.com").rstrip("/")
        self.model = model or "deepseek-chat"
        self.timeout = timeout

    def _endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _raise_http_error(self, res: requests.Response) -> None:
        detail = res.text[:500]
        try:
            body = res.json()
            err = body.get("error") or body
            if isinstance(err, dict):
                detail = err.get("message") or str(err)
            else:
                detail = str(err)
        except Exception:
            pass
        raise RuntimeError(f"DeepSeek API 错误 ({res.status_code}): {detail}")

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        stream: bool,
        thinking_enabled: bool,
        reasoning_effort: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            # 工具调用与思考模式不宜同时开启
            thinking_enabled = False
        if thinking_enabled and model_supports_thinking(self.model):
            effort = (reasoning_effort or "high").strip().lower()
            if effort not in ("high", "max"):
                effort = "high"
            payload["reasoning_effort"] = effort
            payload["thinking"] = {"type": "enabled"}
        elif model_supports_thinking(self.model):
            payload["thinking"] = {"type": "disabled"}
        return payload

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        thinking_enabled: bool = False,
        reasoning_effort: str = "high",
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("未配置 DeepSeek API Key")

        payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            thinking_enabled=thinking_enabled,
            reasoning_effort=reasoning_effort,
        )

        try:
            res = requests.post(
                self._endpoint(),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.error("DeepSeek 请求失败: %s", exc)
            raise RuntimeError(f"无法连接 DeepSeek：{exc}") from exc

        if res.status_code >= 400:
            self._raise_http_error(res)

        data = res.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("DeepSeek 返回为空")
        message = choices[0].get("message") or {}
        content = (message.get("content") or "").strip()
        if not content:
            raise RuntimeError("模型未返回文本内容")
        usage = data.get("usage") or {}
        return {"content": content, "usage": usage, "model": data.get("model") or self.model}

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        thinking_enabled: bool = False,
        reasoning_effort: str = "high",
    ) -> dict[str, Any]:
        """返回 assistant message（可含 tool_calls）。"""
        if not self.api_key:
            raise ValueError("未配置 DeepSeek API Key")

        payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            thinking_enabled=thinking_enabled,
            reasoning_effort=reasoning_effort,
            tools=tools,
        )

        try:
            res = requests.post(
                self._endpoint(),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.error("DeepSeek 请求失败: %s", exc)
            raise RuntimeError(f"无法连接 DeepSeek：{exc}") from exc

        if res.status_code >= 400:
            self._raise_http_error(res)

        data = res.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("DeepSeek 返回为空")
        message = choices[0].get("message") or {}
        usage = data.get("usage") or {}
        return {
            "message": message,
            "usage": usage,
            "model": data.get("model") or self.model,
        }

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        thinking_enabled: bool = False,
        reasoning_effort: str = "high",
    ) -> Iterator[str]:
        """逐块产出正文 delta（忽略 reasoning_content 思考链）。"""
        if not self.api_key:
            raise ValueError("未配置 DeepSeek API Key")

        payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            thinking_enabled=thinking_enabled,
            reasoning_effort=reasoning_effort,
        )

        try:
            res = requests.post(
                self._endpoint(),
                json=payload,
                headers=self._headers(),
                timeout=(10, self.timeout),
                stream=True,
            )
        except requests.RequestException as exc:
            logger.error("DeepSeek 流式请求失败: %s", exc)
            raise RuntimeError(f"无法连接 DeepSeek：{exc}") from exc

        if res.status_code >= 400:
            self._raise_http_error(res)

        for raw_line in res.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data: "):
                continue
            data = raw_line[6:].strip()
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            # 思考链在 reasoning_content，桌宠只展示/朗读最终 content
            content = delta.get("content") or ""
            if content:
                yield content
