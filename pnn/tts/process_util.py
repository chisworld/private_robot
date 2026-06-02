from __future__ import annotations

import logging
import subprocess
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _port_from_url(server_url: str) -> int | None:
    parsed = urlparse(server_url if "://" in server_url else f"http://{server_url}")
    if parsed.port:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    return 80 if parsed.scheme == "http" else None


def kill_process_listening_on_port(port: int) -> bool:
    """终止占用指定端口的进程（Windows）。"""
    if port <= 0:
        return False

    try:
        output = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        logger.debug("netstat failed: %s", exc)
        return False

    pids: set[int] = set()
    needle = f":{port} "
    for line in output.splitlines():
        if needle not in line or "LISTENING" not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue

    killed = False
    for pid in pids:
        if pid <= 0:
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                check=False,
                capture_output=True,
            )
            logger.info("已终止占用端口 %s 的进程 PID=%s", port, pid)
            killed = True
        except Exception as exc:
            logger.debug("taskkill PID %s failed: %s", pid, exc)
    return killed


def kill_server_on_url(server_url: str) -> bool:
    port = _port_from_url(server_url)
    if port is None:
        return False
    return kill_process_listening_on_port(port)
