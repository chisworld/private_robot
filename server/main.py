from __future__ import annotations

import asyncio
import logging

from pnn.core.env import load_env

load_env()

from pnn.core.cuda_runtime import setup_cuda_dlls

setup_cuda_dlls()

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from pnn.asr.service import asr_service
from pnn.core.paths import PROJECT_ROOT
from pnn.tts.service import tts_service
from server.routes.asr import router as asr_router
from server.routes.chat import router as chat_router
from server.routes.dialog import router as dialog_router
from server.routes.characters import router as characters_router
from server.routes.memory import router as memory_router
from server.routes.translate import router as translate_router
from server.routes.tts import router as tts_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="PNN Garden API",
    version="0.2.0",
    description="本地 AI Agent 网关：ASR / TTS / LLM / MCP",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(asr_router)
app.include_router(chat_router)
app.include_router(dialog_router)
app.include_router(memory_router)
app.include_router(characters_router)
app.include_router(tts_router)
app.include_router(translate_router)

# 桌宠静态页与 Live2D 资源（不经过 Next，避免 public 新文件 404）
_WEB_PUBLIC = PROJECT_ROOT / "apps" / "web" / "public"
if _WEB_PUBLIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(_WEB_PUBLIC)), name="static")


@app.websocket("/ws/asr")
async def asr_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    asr_service.register_ws(websocket)
    await websocket.send_json({"type": "status", "status": asr_service.get_config()["status"]})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        asr_service.unregister_ws(websocket)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    from pnn.memory.service import memory_service

    try:
        n = await asyncio.to_thread(memory_service.flush_all_session_writes)
        if n:
            logger.info("API 关闭：已批量写入 %s 轮对话记忆", n)
    except Exception as exc:
        logger.warning("API 关闭时写入记忆失败: %s", exc)


@app.on_event("startup")
async def on_startup() -> None:
    from pnn.core.logging import setup_logging

    setup_logging()
    asr_service.attach_loop(asyncio.get_running_loop())
    cfg = asr_service.get_config()
    if cfg.get("model_warning"):
        logger.warning("%s", cfg["model_warning"])

    tts_service.bootstrap()
    import threading

    def _boot_tts() -> None:
        try:
            tts_service.preload(wait_ready=False)
        except Exception as exc:
            logger.error("TTS 启动预热失败: %s", exc)

    threading.Thread(target=_boot_tts, name="tts-boot-startup", daemon=True).start()


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "modules": {
            "asr": True,
            "tts": False,
            "llm": True,
            "agent": False,
            "mcp": False,
        },
    }


@app.get("/api/health/full")
async def health_full() -> dict:
    tts = await asyncio.to_thread(tts_service.check_server)
    return {
        "status": "ok",
        "modules": {
            "asr": True,
            "tts": tts.get("ok", False),
            "llm": True,
            "agent": False,
            "mcp": False,
        },
    }


def main() -> None:
    from pnn.core.logging import setup_logging

    setup_logging()
    import uvicorn

    uvicorn.run("server.main:app", host="127.0.0.1", port=8765, reload=False, log_level="info")


if __name__ == "__main__":
    main()
