from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pnn.core.blocking import run_blocking
from pnn.memory.config_store import MEMORY_TOP_K_MAX, MEMORY_TOP_K_MIN
from pnn.memory.service import memory_service
router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryConfigUpdate(BaseModel):
    enabled: bool | None = None
    top_k: int | None = Field(default=None, ge=MEMORY_TOP_K_MIN, le=MEMORY_TOP_K_MAX)
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
    return await run_blocking(memory_service.get_config)


@router.put("/config")
async def update_memory_config(body: MemoryConfigUpdate) -> dict:
    payload = body.model_dump(exclude_none=True)
    return await run_blocking(memory_service.update_config, **payload)


@router.get("/list")
async def list_memories(
    limit: int = 50,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    kind: str | None = None,
) -> dict:
    limit = max(1, min(500, limit))
    items = await run_blocking(
        memory_service.list_memories,
        limit,
        q=q,
        date_from=date_from,
        date_to=date_to,
        kind=kind,
    )
    return {"items": items}


@router.get("/dialogue-history")
async def dialogue_history(limit: int = 500, days: int = 60) -> dict:
    limit = max(1, min(1000, limit))
    days = max(1, min(365, days))
    items = await run_blocking(memory_service.list_dialogue_history, limit, days=days)
    return {"items": items, "read_only": True}


@router.get("/stats")
async def memory_stats() -> dict:
    return await run_blocking(memory_service.memory_stats)


@router.get("/kinds")
async def memory_kinds() -> dict:
    from pnn.memory.kinds import KIND_CATALOG

    return {
        "items": [
            {
                "kind": m.kind,
                "label": m.label,
                "description": m.description,
                "color": m.color,
            }
            for m in KIND_CATALOG
        ]
    }


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str) -> dict:
    await run_blocking(memory_service.delete_memory, memory_id)
    return {"ok": True}


@router.post("/diary")
async def write_diary(body: DiaryWrite) -> dict:
    try:
        return await run_blocking(memory_service.write_diary_now, body.summary)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
