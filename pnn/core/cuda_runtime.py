from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CUDA_DLL_ROOT = _PROJECT_ROOT / "CUDA_DLL"
_CONFIGURED = False
_ADDED_DIRS: list[str] = []


def discover_cuda_dll_dirs() -> list[Path]:
    """扫描 CUDA_DLL 下包含 .dll 的目录。"""
    if not _CUDA_DLL_ROOT.is_dir():
        return []

    dirs: list[Path] = []
    if any(_CUDA_DLL_ROOT.glob("*.dll")):
        dirs.append(_CUDA_DLL_ROOT)

    for item in sorted(_CUDA_DLL_ROOT.iterdir()):
        if item.is_dir() and any(item.glob("*.dll")):
            dirs.append(item)

    return dirs


def setup_cuda_dlls() -> list[str]:
    """将项目 CUDA_DLL 目录加入 Windows DLL 搜索路径（需在导入 faster_whisper 之前调用）。"""
    global _CONFIGURED

    if _CONFIGURED:
        return list(_ADDED_DIRS)

    if sys.platform != "win32":
        _CONFIGURED = True
        return []

    for dll_dir in discover_cuda_dll_dirs():
        path_str = str(dll_dir.resolve())
        if path_str in _ADDED_DIRS:
            continue

        os.environ["PATH"] = path_str + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(path_str)
            except OSError as exc:
                logger.warning("无法注册 DLL 目录 %s: %s", path_str, exc)

        _ADDED_DIRS.append(path_str)
        logger.info("已加载 CUDA DLL 目录: %s", path_str)

    _CONFIGURED = True
    return list(_ADDED_DIRS)
