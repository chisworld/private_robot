"""桌面宠物宿主 — pywebview 独立窗口，加载 /pet 页面"""

from __future__ import annotations

import sys
import time
import subprocess
import urllib.request
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [PET] %(message)s")
logger = logging.getLogger("pet")

PET_URL = "http://localhost:3000/pet"
API_PORT = 8765
WEB_PORT = 3000


def wait_for_url(url: str, timeout: float = 30) -> bool:
    """轮询等待 URL 可访问"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def start_server() -> subprocess.Popen | None:
    """若 API 未运行则启动 server.main"""
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/api/health", timeout=2)
        logger.info("API 服务已在运行")
        return None
    except Exception:
        pass

    logger.info("启动 API 服务…")
    proc = subprocess.Popen(
        [sys.executable, "-m", "server.main"],
        cwd=__import__("pathlib").Path(__file__).resolve().parent.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not wait_for_url(f"http://127.0.0.1:{API_PORT}/api/health"):
        logger.error("API 启动超时")
        proc.terminate()
        return None
    logger.info("API 就绪")
    return proc


def main() -> None:
    import webview

    api_proc = start_server()

    # 等待前端就绪
    if not wait_for_url(f"http://localhost:{WEB_PORT}"):
        logger.warning("前端服务未检测到，请先启动: cd apps/web && npm run dev")

    # 创建桌面宠物窗口
    window = webview.create_window(
        title="14酱",
        url=PET_URL,
        width=340,
        height=620,
        frameless=True,
        on_top=True,
        easy_drag=True,
        transparent=False,
        background_color="#00000000",
        resizable=False,
        minimized=False,
    )

    webview.start(gui="edgechromium", debug=False)

    # 清理
    if api_proc:
        api_proc.terminate()


if __name__ == "__main__":
    main()
