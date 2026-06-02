from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from pnn.tts.service import SUPPORTED_PROVIDERS, SUPPORTED_TEXT_LANGS, tts_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])

_AUDIO_SUFFIX = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}


def _resolve_audio_file(path: str) -> Path:
    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在")
    if file_path.suffix.lower() not in _AUDIO_SUFFIX:
        raise HTTPException(status_code=400, detail="不支持的音频格式")
    return file_path


class EmotionPresetModel(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    ref_audio_path: str = ""
    prompt_text: str = ""
    prompt_lang: str = ""


class TtsConfigUpdate(BaseModel):
    provider: str | None = None
    server_url: str | None = None
    work_path: str | None = None
    api_key: str | None = None
    gpt_model_path: str | None = None
    sovits_model_path: str | None = None
    ref_audio_path: str | None = None
    prompt_text: str | None = None
    prompt_lang: str | None = None
    text_lang: str | None = None
    speed_factor: float | None = Field(default=None, ge=0.5, le=2.0)
    auto_start_server: bool | None = None
    character_name: str | None = None
    onnx_model_dir: str | None = None
    emotion_presets: list[EmotionPresetModel] | None = None
    active_emotion_id: str | None = None


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1)
    text_lang: str | None = None
    emotion_id: str | None = None


@router.get("/languages")
def list_languages() -> dict:
    return {"languages": SUPPORTED_TEXT_LANGS}


@router.get("/providers")
def list_providers() -> dict:
    return {"providers": SUPPORTED_PROVIDERS}


@router.get("/config")
def get_config() -> dict:
    return tts_service.get_config()


@router.put("/config")
def update_config(body: TtsConfigUpdate) -> dict:
    payload = body.model_dump(exclude_none=True)
    if "emotion_presets" in payload:
        payload["emotion_presets"] = [item for item in payload["emotion_presets"]]
    return tts_service.update_config(**payload)


@router.get("/health")
def health() -> dict:
    return tts_service.check_server()


@router.post("/preload")
def preload_tts(wait: bool = False) -> dict:
    """加载配置并后台预热 GPT-SoVITS（wait=true 时阻塞至就绪）。"""
    try:
        return tts_service.preload(wait_ready=wait)
    except Exception as exc:
        logger.exception("TTS preload failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/server/start")
def start_server() -> dict:
    """同步启动，避免 asyncio 线程池 shutdown 导致桌宠 TTS 失败。"""
    try:
        return tts_service.begin_start_server()
    except Exception as exc:
        logger.exception("TTS server start failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/server/stop")
def stop_server() -> dict:
    tts_service.stop_server()
    return {"ok": True}


@router.get("/reference/preview")
def preview_reference(path: str) -> FileResponse:
    file_path = _resolve_audio_file(path)
    media_type = _AUDIO_SUFFIX.get(file_path.suffix.lower(), "audio/wav")
    return FileResponse(path=str(file_path), media_type=media_type, filename=file_path.name)


@router.post("/synthesize")
def synthesize(body: SynthesizeRequest) -> FileResponse:
    preview = body.text.replace("\n", " ")[:64]
    if len(body.text) > 64:
        preview += "…"
    logger.info("TTS 合成开始（%d 字）: %s", len(body.text), preview)
    if body.text_lang:
        tts_service._config.text_lang = body.text_lang
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp_path = tmp.name
        path = tts_service.synthesize(
            body.text,
            output_path=tmp_path,
            emotion_id=body.emotion_id,
        )
        logger.info("TTS 合成完成 → %s", path)
        return FileResponse(
            path=str(path),
            media_type="audio/wav",
            filename=Path(path).name,
        )
    except Exception as exc:
        logger.exception("TTS synthesize failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
