"""模型资源与下载地址 API。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from pnn.core.model_downloads import model_downloads_payload

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/downloads")
async def list_downloads(
    category: str | None = Query(
        default=None,
        description="筛选类别：asr | tts | llm_local",
    ),
) -> dict:
    return model_downloads_payload(category=category)
