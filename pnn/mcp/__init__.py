"""MCP（Model Context Protocol）工具集成。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pnn.mcp.service import McpService

__all__ = ["McpService", "mcp_service"]


def __getattr__(name: str) -> Any:
    if name == "McpService":
        from pnn.mcp.service import McpService

        return McpService
    if name == "mcp_service":
        from pnn.mcp.service import mcp_service

        return mcp_service
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
