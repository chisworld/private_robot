"""快捷启动 HTTP 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pnn.core.blocking import run_blocking
from pnn.launch_apps.service import launch_apps_service

router = APIRouter(prefix="/api/launch-apps", tags=["launch-apps"])


class LaunchAppEntryUpdate(BaseModel):
    id: str = Field(min_length=1)
    label: str = ""
    aliases: list[str] = Field(default_factory=list)
    path: str = ""
    args: list[str] = Field(default_factory=list)
    enabled: bool = True


class FolderEntryUpdate(BaseModel):
    id: str = Field(min_length=1)
    label: str = ""
    aliases: list[str] = Field(default_factory=list)
    path: str = ""
    enabled: bool = True


class UrlEntryUpdate(BaseModel):
    id: str = Field(min_length=1)
    label: str = ""
    aliases: list[str] = Field(default_factory=list)
    url: str = ""
    enabled: bool = True


class LaunchAppsConfigUpdate(BaseModel):
    enabled: bool | None = None
    use_in_chat: bool | None = None
    apps: list[LaunchAppEntryUpdate] | None = None
    folders: list[FolderEntryUpdate] | None = None
    urls: list[UrlEntryUpdate] | None = None


@router.get("/config")
async def get_launch_apps_config() -> dict:
    return launch_apps_service.get_config()


@router.put("/config")
async def update_launch_apps_config(body: LaunchAppsConfigUpdate) -> dict:
    apps = None
    if body.apps is not None:
        apps = [item.model_dump() for item in body.apps]
    folders = None
    if body.folders is not None:
        folders = [item.model_dump() for item in body.folders]
    urls = None
    if body.urls is not None:
        urls = [item.model_dump() for item in body.urls]
    cfg = await run_blocking(
        launch_apps_service.update_config,
        enabled=body.enabled,
        use_in_chat=body.use_in_chat,
        apps=apps,
        folders=folders,
        urls=urls,
    )
    return {"ok": True, "config": launch_apps_service.get_config(), "enabled": cfg.enabled}


@router.post("/config/reload")
async def reload_launch_apps_config() -> dict:
    cfg = await run_blocking(launch_apps_service.reload_config)
    return {
        "ok": True,
        "enabled": cfg.enabled,
        "apps": len(cfg.apps),
        "folders": len(cfg.folders),
        "urls": len(cfg.urls),
    }
