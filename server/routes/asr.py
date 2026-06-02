from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from pnn.core.async_bridge import run_sync
from pnn.asr.service import asr_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["asr"])


class AsrConfigUpdate(BaseModel):
    model: str | None = None
    model_path: str | None = None
    device: str | None = None
    compute_type: str | None = None
    language: str | None = None
    silence_duration: float | None = Field(default=None, ge=0.2, le=3.0)
    partial_interval: float | None = Field(default=None, ge=0.3, le=5.0)
    energy_threshold: float | None = Field(default=None, ge=0.001, le=0.8)


@router.get("/models")
async def list_models() -> dict:
    return asr_service.list_models()


@router.get("/config")
async def get_config() -> dict:
    return asr_service.get_config()


@router.put("/config")
async def update_config(body: AsrConfigUpdate) -> dict:
    payload = body.model_dump(exclude_none=True)
    available = asr_service.list_models()["models"]
    if "model" in payload and payload["model"] not in available:
        raise HTTPException(status_code=400, detail=f"不支持的模型: {payload['model']}")
    try:
        return asr_service.update_config(**payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/stream/start")
async def start_stream() -> dict:
    started = asr_service.begin_start_stream()
    if not started:
        return {"ok": True, "status": asr_service.get_config()["status"]}
    return {"ok": True, "status": "loading"}


@router.post("/stream/stop")
async def stop_stream() -> dict:
    asr_service.stop_stream()
    return {"ok": True, "status": "idle"}


@router.post("/transcribe")
async def transcribe_file(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        return await run_sync(asr_service.transcribe_upload, tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)
