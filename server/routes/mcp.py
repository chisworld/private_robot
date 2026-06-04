"""MCP HTTP 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pnn.core.blocking import run_blocking
from pnn.mcp.config_store import MAX_AGENT_STEPS_LIMIT
from pnn.mcp.service import mcp_service

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class McpToolCallRequest(BaseModel):
    server_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class McpConfigUpdate(BaseModel):
    enabled: bool | None = None
    use_in_chat: bool | None = None
    max_agent_steps: int | None = Field(default=None, ge=1, le=MAX_AGENT_STEPS_LIMIT)
    tool_result_max_chars: int | None = Field(default=None, ge=500, le=50000)
    default_call_timeout: float | None = Field(default=None, ge=5.0, le=600.0)
    preload_on_startup: bool | None = None
    server_enabled: dict[str, bool] | None = None
    playwright_headless: bool | None = None


@router.get("/config")
async def get_mcp_config() -> dict:
    return mcp_service.get_config()


@router.put("/config")
async def update_mcp_config(body: McpConfigUpdate) -> dict:
    payload = body.model_dump(exclude_none=True)
    server_enabled = payload.pop("server_enabled", None)
    try:
        cfg = await run_blocking(
            mcp_service.update_config,
            server_enabled=server_enabled,
            **payload,
        )
        return {"ok": True, "config": mcp_service.get_config(), "enabled": cfg.enabled}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/config/reload")
async def reload_mcp_config() -> dict:
    try:
        cfg = await run_blocking(mcp_service.reload_config)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "enabled": cfg.enabled, "servers": len(cfg.servers)}


@router.get("/status")
async def mcp_status() -> dict:
    cfg = mcp_service.get_config()
    return {
        **cfg,
        "ready": mcp_service.is_ready(),
        "agent_ready": mcp_service.chat_enabled(),
    }


@router.post("/servers/{server_id}/connect")
async def connect_mcp_server(server_id: str) -> dict:
    try:
        return await run_blocking(mcp_service.connect_server, server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/tools")
async def list_mcp_tools(connect: bool = True) -> dict:
    try:
        tools = await run_blocking(mcp_service.list_tools, connect=connect)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"tools": tools, "count": len(tools)}


@router.post("/tools/call")
async def call_mcp_tool(body: McpToolCallRequest) -> dict:
    try:
        return await run_blocking(
            mcp_service.call_tool,
            server_id=body.server_id,
            tool_name=body.tool_name,
            arguments=body.arguments,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
