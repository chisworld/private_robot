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


def _is_local_openai_base(base_url: str) -> bool:
    b = (base_url or "").strip().lower()
    return b.startswith("http://127.0.0.1") or b.startswith("http://localhost")


def coalesce_messages_for_local_llm(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """llama.cpp Qwen 等模板要求 system 仅在开头且通常合并为一条。"""
    if not messages:
        return messages
    leading_system: list[str] = []
    rest: list[dict[str, Any]] = []
    past_leading = False
    for msg in messages:
        role = (msg.get("role") or "").strip()
        content = (msg.get("content") or "").strip()
        if not past_leading and role == "system":
            if content:
                leading_system.append(content)
            continue
        past_leading = True
        if role == "system" and content:
            # 不应出现在对话中间；并入下一条 user 或单独作为 user 提示
            rest.append({"role": "user", "content": f"[系统提示]\n{content}"})
            continue
        if content or role in ("user", "assistant", "tool"):
            rest.append(msg)
    out: list[dict[str, Any]] = []
    if leading_system:
        out.append({"role": "system", "content": "\n\n".join(leading_system)})
    out.extend(rest)
    return out


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
        self.timeout = 600.0 if _is_local_openai_base(self.base_url) else timeout

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
        raise RuntimeError(
            f"{'本地 LLM' if _is_local_openai_base(self.base_url) else 'DeepSeek API'} "
            f"错误 ({res.status_code}): {detail}"
        )

    @staticmethod
    def _prepare_messages(
        messages: list[dict[str, Any]], base_url: str
    ) -> list[dict[str, Any]]:
        if _is_local_openai_base(base_url):
            return coalesce_messages_for_local_llm(messages)
        return messages

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
        if _is_local_openai_base(self.base_url):
            messages = coalesce_messages_for_local_llm(messages)
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
        if _is_local_openai_base(self.base_url):
            # Qwen3 默认走 reasoning_content，桌宠需要直接可读的正文 content
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            return payload
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

        msgs = self._prepare_messages(messages, self.base_url)
        payload = self._build_payload(
            msgs,
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
        if not content and _is_local_openai_base(self.base_url):
            content = (message.get("reasoning_content") or "").strip()
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

        msgs = self._prepare_messages(messages, self.base_url)
        payload = self._build_payload(
            msgs,
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

        msgs = self._prepare_messages(messages, self.base_url)
        payload = self._build_payload(
            msgs,
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

        res.encoding = "utf-8"
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
            content = delta.get("content") or delta.get("text") or ""
            if not content:
                content = choices[0].get("text") or ""
            if not content and _is_local_openai_base(self.base_url):
                content = delta.get("reasoning_content") or ""
            if content:
                yield content
