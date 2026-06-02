from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pnn.translate.service import translate_service

router = APIRouter(prefix="/api/translate", tags=["translate"])


class TranslateBody(BaseModel):
    text: str = Field(min_length=1)


@router.get("/config")
async def get_translate_config() -> dict:
    return translate_service.get_config()


@router.put("/config")
async def update_translate_config(body: dict) -> dict:
    allowed = {
        "enabled",
        "provider",
        "app_id",
        "secret",
        "from_lang",
        "to_lang",
    }
    payload = {k: v for k, v in body.items() if k in allowed}
    return translate_service.update_config(**payload)


@router.post("")
async def translate_text(body: TranslateBody) -> dict:
    try:
        out = await asyncio.to_thread(translate_service.to_display_chinese, body.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"text": out, "source": body.text}
