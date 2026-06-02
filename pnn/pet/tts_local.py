"""桌宠侧本地拉起 GPT-SoVITS（API 不可用时兜底）。"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

from pnn.core.paths import PROJECT_ROOT
from pnn.tts.probe import probe_http_server

logger = logging.getLogger(__name__)

_TTS_CONFIG = PROJECT_ROOT / "data" / "config" / "tts.json"
_PROCESS: subprocess.Popen | None = None


def _load_config() -> dict:
    if not _TTS_CONFIG.is_file():
        return {}
    return json.loads(_TTS_CONFIG.read_text(encoding="utf-8"))


def start_local_server(*, wait_ready: bool = True, timeout: float = 180.0) -> bool:
    """直接启动 9880 子进程，不经过 FastAPI asyncio。"""
    global _PROCESS
    cfg = _load_config()
    work_path = cfg.get("work_path")
    server_url = (cfg.get("server_url") or "http://127.0.0.1:9880").rstrip("/") + "/"
    if not work_path:
        logger.error("tts.json 未配置 work_path")
        return False

    root = Path(work_path)
    python_exe = root / "runtime" / "python.exe"
    api_py = root / "api_v2.py"
    if not python_exe.is_file() or not api_py.is_file():
        logger.error("GPT-SoVITS 路径无效: %s", root)
        return False

    if probe_http_server(server_url):
        logger.info("GPT-SoVITS 已在运行: %s", server_url)
        return True

    if _PROCESS is not None and _PROCESS.poll() is None:
        logger.info("GPT-SoVITS 进程已在启动中")
    else:
        _PROCESS = subprocess.Popen(
            [str(python_exe), str(api_py)],
            cwd=str(root),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        logger.info("已本地启动 GPT-SoVITS → %s", server_url)

    if not wait_ready:
        return True

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe_http_server(server_url):
            return True
        time.sleep(2.0)
    return False
