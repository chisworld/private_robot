from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from pnn.asr.service import asr_service
from pnn.core.blocking import init_blocking_pool, run_blocking, shutdown_blocking_pool
from pnn.core.env import load_env
from pnn.core.paths import PROJECT_ROOT
from pnn.tts.service import tts_service
from server.routes.asr import router as asr_router
from server.routes.chat import router as chat_router
from server.routes.dialog import router as dialog_router
from server.routes.characters import router as characters_router
from server.routes.memory import router as memory_router
from server.routes.mcp import router as mcp_router
from server.routes.translate import router as translate_router
from server.routes.tts import router as tts_router

load_env()

from pnn.core.cuda_runtime import setup_cuda_dlls

setup_cuda_dlls()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from pnn.core.logging import setup_logging

    setup_logging()
    init_blocking_pool()
    loop = asyncio.get_running_loop()
    asr_service.attach_loop(loop)
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

    from pnn.mcp.service import mcp_service

    def _boot_mcp() -> None:
        try:
            mcp_service.bootstrap()
        except Exception as exc:
            logger.warning("MCP 启动预热失败: %s", exc)

    threading.Thread(target=_boot_mcp, name="mcp-boot-startup", daemon=True).start()
    yield
    asr_service.attach_loop(None)
    try:
        mcp_service.shutdown()
    except Exception as exc:
        logger.warning("MCP 关闭失败: %s", exc)
    shutdown_blocking_pool()
    from pnn.memory.service import memory_service

    try:
        n = memory_service.flush_all_session_writes()
        if n:
            logger.info("API 关闭：已批量写入 %s 轮对话记忆", n)
    except Exception as exc:
        logger.warning("API 关闭时写入记忆失败: %s", exc)


app = FastAPI(
    title="PNN Garden API",
    version="0.2.0",
    description="本地 AI Agent 网关：ASR / TTS / LLM / MCP",
    lifespan=lifespan,
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
app.include_router(mcp_router)

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


@app.get("/api/health")
async def health() -> dict:
    from pnn.mcp.service import mcp_service

    return {
        "status": "ok",
        "modules": {
            "asr": True,
            "tts": False,
            "llm": True,
            "agent": False,
            "mcp": mcp_service.sdk_ok(),
        },
    }


@app.get("/api/health/full")
async def health_full() -> dict:
    from pnn.mcp.service import mcp_service

    tts = await run_blocking(tts_service.check_server)
    agent_on = await run_blocking(llm_service.agent_enabled)
    return {
        "status": "ok",
        "modules": {
            "asr": True,
            "tts": tts.get("ok", False),
            "llm": True,
            "agent": agent_on,
            "mcp": mcp_service.sdk_ok() and mcp_service.is_ready(),
        },
        "mcp": mcp_service.get_config(),
    }


def main() -> None:
    from pnn.core.logging import run_uvicorn, setup_logging

    setup_logging()
    run_uvicorn("server.main:app", port=8765, reload=False)


if __name__ == "__main__":
    main()
