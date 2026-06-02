from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pnn.memory.service import memory_service

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryConfigUpdate(BaseModel):
    enabled: bool | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    extraction_enabled: bool | None = None
    core_card: str | None = None
    decay_per_day: float | None = Field(default=None, ge=0.0, le=0.5)
    min_score: float | None = Field(default=None, ge=0.01, le=1.0)
    diary_enabled: bool | None = None
    merge_similar_with_llm: bool | None = None


class DiaryWrite(BaseModel):
    summary: str = Field(min_length=1)


@router.get("/config")
async def get_memory_config() -> dict:
    return await asyncio.to_thread(memory_service.get_config)


@router.put("/config")
async def update_memory_config(body: MemoryConfigUpdate) -> dict:
    payload = body.model_dump(exclude_none=True)
    return memory_service.update_config(**payload)


@router.get("/list")
async def list_memories(limit: int = 50) -> dict:
    limit = max(1, min(200, limit))
    return {"items": await asyncio.to_thread(memory_service.list_memories, limit)}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str) -> dict:
    await asyncio.to_thread(memory_service.delete_memory, memory_id)
    return {"ok": True}


@router.post("/diary")
async def write_diary(body: DiaryWrite) -> dict:
    try:
        return await asyncio.to_thread(memory_service.write_diary_now, body.summary)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
