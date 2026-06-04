from __future__ import annotations

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """统一日志格式，输出到终端。"""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    for name in ("server", "pnn", "pnn.asr", "uvicorn", "uvicorn.error"):
        logging.getLogger(name).setLevel(level)
    # 不输出每条 HTTP 请求（GET /api/... 200 OK）
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("faster_whisper", "ctranslate2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("pnn.asr.stream").setLevel(logging.WARNING)


def run_uvicorn(app: str, *, host: str = "127.0.0.1", port: int = 8765, **kwargs) -> None:
    """启动 FastAPI；关闭访问日志与 ANSI 颜色，避免 Windows 终端出现 \\x1b[32m 乱码。"""
    import uvicorn

    uvicorn.run(
        app,
        host=host,
        port=port,
        access_log=False,
        use_colors=False,
        log_level="info",
        **kwargs,
    )
