"""设置页批量保存（减少 HTTP 往返与 MCP 重复断开）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pnn.core.blocking import run_blocking
from pnn.settings.batch_save import apply_settings_batch

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsBatchSave(BaseModel):
    char_id: str = ""
    mcp_skip: bool = False
    mcp: dict[str, Any] | None = None
    tts: dict[str, Any] | None = None
    pack: dict[str, Any] | None = None
    llm: dict[str, Any] | None = None
    asr: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    translate: dict[str, Any] | None = None


@router.post("/save")
async def save_settings(body: SettingsBatchSave) -> dict:
    try:
        return await run_blocking(apply_settings_batch, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
