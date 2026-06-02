from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import requests

logger = logging.getLogger(__name__)


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

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("未配置 DeepSeek API Key")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

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

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        """逐块产出文本 delta（OpenAI SSE 格式）。"""
        if not self.api_key:
            raise ValueError("未配置 DeepSeek API Key")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

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
            content = delta.get("content") or ""
            if content:
                yield content
