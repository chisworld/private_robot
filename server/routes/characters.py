from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pnn.characters.pack import CharacterPack, TtsPackSettings
from pnn.characters.service import character_pack_service
from pnn.core.blocking import run_blocking

router = APIRouter(prefix="/api/characters", tags=["characters"])


class TtsPackBody(BaseModel):
    ref_audio_path: str = ""
    prompt_text: str = ""
    prompt_lang: str = "ja"
    text_lang: str = "ja"
    gpt_model_path: str = ""
    sovits_model_path: str = ""
    speed_factor: float = 1.0


class CharacterPackBody(BaseModel):
    name: str = ""
    character_prompt: str = ""
    live2d_model_dir: str = "live2d/14酱"
    tts: TtsPackBody | None = None
    memory_core_card: str = ""
    reply_language: str = "ja"


class CreatePackBody(BaseModel):
    id: str = Field(min_length=1)
    name: str = ""
    clone_from: str | None = None


@router.get("/packs")
async def list_packs() -> dict:
    return {"items": await run_blocking(character_pack_service.list_packs)}


@router.get("/packs/{char_id}")
async def get_pack(char_id: str) -> dict:
    pack = await run_blocking(character_pack_service.get_pack, char_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="角色包不存在")
    return pack.to_dict()


@router.put("/packs/{char_id}")
async def save_pack_route(char_id: str, body: CharacterPackBody) -> dict:
    existing = await run_blocking(character_pack_service.get_pack, char_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="角色包不存在")
    pack = CharacterPack(
        id=char_id,
        name=body.name or existing.name,
        character_prompt=body.character_prompt,
        live2d_model_dir=body.live2d_model_dir or existing.live2d_model_dir,
        live2d_variants=list(existing.live2d_variants),
        tts=existing.tts,
        memory_core_card=body.memory_core_card,
        reply_language=body.reply_language or existing.reply_language,
    )
    if body.tts is not None:
        pack.tts = TtsPackSettings.from_dict(body.tts.model_dump())
    saved = await run_blocking(character_pack_service.save_pack_data, pack)
    return saved.to_dict()


@router.post("/packs")
async def create_pack(body: CreatePackBody) -> dict:
    try:
        pack = await run_blocking(
            character_pack_service.create_pack,
            body.id,
            name=body.name,
            clone_from=body.clone_from,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return pack.to_dict()


@router.post("/packs/{char_id}/apply")
async def apply_pack(char_id: str) -> dict:
    try:
        pack = await run_blocking(character_pack_service.apply_pack, char_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "pack": pack.to_dict(), "active_character": pack.id}
