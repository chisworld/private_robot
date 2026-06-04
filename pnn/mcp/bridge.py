"""MCP 客户端桥接（stdio / SSE / streamable HTTP）。"""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


class MCPBridge:
    def __init__(self) -> None:
        self.session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None

    async def _ensure_fresh_stack(self) -> AsyncExitStack:
        await self.close()
        stack = AsyncExitStack()
        await stack.__aenter__()
        self._stack = stack
        return stack

    async def connect_stdio(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        stack = await self._ensure_fresh_stack()
        try:
            params = StdioServerParameters(command=command, args=list(args or []), env=env)
            read, write = await stack.enter_async_context(stdio_client(params))
            self.session = await stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()
        except Exception:
            await self.close()
            raise

    async def connect_sse(self, url: str, headers: dict[str, str] | None = None) -> None:
        stack = await self._ensure_fresh_stack()
        try:
            read, write = await stack.enter_async_context(sse_client(url=url, headers=headers))
            self.session = await stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()
        except Exception:
            await self.close()
            raise

    async def connect_streamable_http(self, url: str, headers: dict[str, str] | None = None) -> None:
        stack = await self._ensure_fresh_stack()
        try:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(url=url, headers=headers)
            )
            self.session = await stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()
        except Exception:
            await self.close()
            raise

    async def list_tools(self) -> list[Any]:
        if self.session is None:
            raise RuntimeError("MCPBridge 未连接")
        tools_res = await self.session.list_tools()
        return list(tools_res.tools)

    @staticmethod
    def _text_from_tool_result(result: Any) -> str:
        parts: list[str] = []
        for block in result.content or []:
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", None)
                if text is not None:
                    parts.append(str(text))
        return "\n".join(parts)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None) -> str:
        if self.session is None:
            raise RuntimeError("MCPBridge 未连接")
        result = await self.session.call_tool(tool_name, arguments or {})
        text = MCPBridge._text_from_tool_result(result)
        if text:
            return text
        if getattr(result, "is_error", False):
            try:
                return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
            except Exception:
                return str(result)
        return ""

    async def close(self) -> None:
        self.session = None
        stack = self._stack
        self._stack = None
        if stack is not None:
            try:
                await stack.__aexit__(None, None, None)
            except Exception:
                logger.debug("MCPBridge.close: teardown warning", exc_info=True)
