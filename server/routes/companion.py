"""代码/写作陪伴 HTTP 路由。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pnn.companion.config_store import load_companion_config
from pnn.companion.runtime import get_companion_runtime

router = APIRouter(prefix="/api/companion", tags=["companion"])


class IdeEventBody(BaseModel):
    kind: Literal["compile_failed", "compile_success", "failed", "success", "error", "ok"] = Field(
        description="编译/构建结果"
    )


@router.get("/config")
async def get_companion_config() -> dict:
    cfg = load_companion_config()
    return {
        "enabled": cfg.enabled,
        "build_watch_enabled": cfg.build_watch_enabled,
        "writing_nudge_enabled": cfg.writing_nudge_enabled,
        "build_log_paths": list(cfg.build_log_paths),
        "build_poll_seconds": cfg.build_poll_seconds,
        "writing_idle_minutes": cfg.writing_idle_minutes,
        "writing_poll_seconds": cfg.writing_poll_seconds,
        "compile_cooldown_seconds": cfg.compile_cooldown_seconds,
    }


@router.post("/ide-event")
async def post_ide_event(body: IdeEventBody) -> dict:
    rt = get_companion_runtime()
    if rt is None:
        return {"ok": False, "error": "桌宠未运行或未加载陪伴模块"}
    rt.notify_ide_event(body.kind)
    return {"ok": True, "kind": body.kind}
