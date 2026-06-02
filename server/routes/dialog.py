from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pnn.core.async_bridge import run_sync
from pnn.ui.file_picker import pick_file, pick_folder

router = APIRouter(prefix="/api/dialog", tags=["dialog"])


class PickFileRequest(BaseModel):
    title: str = "选择文件"
    filetypes: list[list[str]] = Field(default_factory=lambda: [["All files", "*.*"]])
    initial_dir: str | None = None


class PickFolderRequest(BaseModel):
    title: str = "选择文件夹"
    initial_dir: str | None = None


@router.post("/pick-file")
async def dialog_pick_file(body: PickFileRequest) -> dict:
    filetypes = [(item[0], item[1]) for item in body.filetypes if len(item) >= 2]
    path = await run_sync(
        pick_file,
        title=body.title,
        filetypes=filetypes or None,
        initial_dir=body.initial_dir,
    )
    return {"path": path, "cancelled": path is None}


@router.post("/pick-folder")
async def dialog_pick_folder(body: PickFolderRequest) -> dict:
    path = await run_sync(
        pick_folder,
        title=body.title,
        initial_dir=body.initial_dir,
    )
    return {"path": path, "cancelled": path is None}
