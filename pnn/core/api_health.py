"""检测本地 API (8765) 是否真正可用（不仅 /api/health）。"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from pnn.core.paths import api_base_url

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_api_base = api_base_url()
API_HEALTH_URL = f"{_api_base}/api/health"
CHAT_CONFIG_URL = f"{_api_base}/api/chat/config"
MCP_STATUS_URL = f"{_api_base}/api/mcp/status"
MCP_CONFIG_URL = f"{_api_base}/api/mcp/config"
TTS_HEALTH_URL = f"{_api_base}/api/tts/health"
TTS_CONFIG_URL = f"{_api_base}/api/tts/config"
API_PORT = int(_api_base.rsplit(":", 1)[-1])

try:
    from pnn.tts.service import TTS_SERVICE_VERSION as MIN_TTS_SERVICE_VERSION
except ImportError:
    MIN_TTS_SERVICE_VERSION = 7

# 与 server/routes/chat.py 的 STREAM_SSE_VERSION 保持同步
MIN_STREAM_SSE_VERSION = 11


def _urlopen(url: str, *, timeout: float = 3.0, method: str = "GET", data: bytes | None = None):
    proxy = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy)
    req = urllib.request.Request(url, method=method, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    return opener.open(req, timeout=timeout)


def is_api_alive(*, timeout: float = 3.0) -> bool:
    try:
        with _urlopen(API_HEALTH_URL, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return code == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def is_chat_api_ready(*, timeout: float = 3.0) -> bool:
    try:
        with _urlopen(CHAT_CONFIG_URL, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return code == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def is_mcp_api_ready(*, timeout: float = 3.0) -> bool:
    """MCP 路由已挂载（旧版 API 进程会返回 404）。"""
    try:
        with _urlopen(MCP_STATUS_URL, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return code == 200
    except urllib.error.HTTPError as exc:
        return exc.code != 404
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def is_mcp_config_api_ready(*, timeout: float = 3.0) -> bool:
    """MCP 配置接口为当前版本（含 playwright_headless，PUT 可正常保存）。"""
    try:
        with _urlopen(MCP_CONFIG_URL, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            if code != 200:
                return False
            raw = resp.read()
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            return isinstance(data, dict) and "playwright_headless" in data
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False


def chat_stream_sse_version(*, timeout: float = 3.0) -> int:
    try:
        with _urlopen(CHAT_CONFIG_URL, timeout=timeout) as resp:
            raw = resp.read()
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            return int(data.get("stream_sse_version") or 0)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return 0


def chat_api_version_ok(*, timeout: float = 3.0) -> bool:
    return chat_stream_sse_version(timeout=timeout) >= MIN_STREAM_SSE_VERSION


def tts_service_version(*, timeout: float = 3.0) -> int:
    try:
        with _urlopen(TTS_CONFIG_URL, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            if code == 404:
                return 0
            raw = resp.read()
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            return int(data.get("service_version") or 0)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return 0


def tts_api_version_ok(*, timeout: float = 3.0) -> bool:
    return tts_service_version(timeout=timeout) >= MIN_TTS_SERVICE_VERSION


def is_api_ready_for_pet(*, timeout: float = 2.0) -> bool:
    """桌宠开屏用：仅要求 API 存活且对话配置可读（不等待 TTS/MCP 全量就绪）。"""
    return is_api_alive(timeout=timeout) and is_chat_api_ready(timeout=timeout)


def wait_for_api_pet_ready(timeout: float = 45.0, *, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    step = max(0.05, interval)
    while time.monotonic() < deadline:
        if is_api_ready_for_pet(timeout=min(2.0, step + 1.0)):
            return True
        time.sleep(step)
    return False


def is_api_operational(*, timeout: float = 3.0) -> bool:
    """API 能正常处理需线程池的路由（如 TTS health），排除「正在关闭」的僵尸进程。"""
    if not is_api_alive(timeout=timeout):
        return False
    if not is_chat_api_ready(timeout=timeout):
        return False
    if not chat_api_version_ok(timeout=timeout):
        return False
    if not is_mcp_api_ready(timeout=timeout):
        return False
    if not is_mcp_config_api_ready(timeout=timeout):
        return False
    if not tts_api_version_ok(timeout=timeout):
        return False
    try:
        with _urlopen(TTS_HEALTH_URL, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            if code != 200:
                return False
            raw = resp.read()
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            return isinstance(data, dict)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False


def _pids_on_port(port: int) -> list[int]:
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    needle = f":{port}"
    pids: list[int] = []
    for line in out.splitlines():
        if "LISTENING" not in line.upper() or needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def kill_api_on_port() -> bool:
    pids = _pids_on_port(API_PORT)
    if not pids:
        return False
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            check=False,
            capture_output=True,
        )
    for _ in range(8):
        time.sleep(0.5)
        if not _pids_on_port(API_PORT):
            return True
    logger.warning("端口 %s 仍被占用: %s", API_PORT, _pids_on_port(API_PORT))
    return True


def wait_for_api_operational(timeout: float = 60.0, *, interval: float = 0.15) -> bool:
    deadline = time.monotonic() + timeout
    step = max(0.05, interval)
    while time.monotonic() < deadline:
        if is_api_operational(timeout=min(2.0, step + 1.0)):
            return True
        time.sleep(step)
    return False


def start_api_subprocess() -> subprocess.Popen:
    log_dir = _ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "api_boot.log"
    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(f"\n--- API start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_file.flush()
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(
        [sys.executable, "-m", "server.main"],
        cwd=str(_ROOT),
        creationflags=flags,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def restart_api(*, timeout: float = 60.0) -> bool:
    """强制结束 8765 上的 API 并启动新进程（用于 MCP 配置升级后）。"""
    logger.info("强制重启 API…")
    if is_api_alive() or _pids_on_port(API_PORT):
        kill_api_on_port()
        time.sleep(0.5)
    proc = start_api_subprocess()
    ok = wait_for_api_operational(timeout=timeout)
    if not ok:
        try:
            proc.terminate()
        except Exception:
            pass
    return ok


def ensure_api_for_pet(*, timeout: float = 60.0) -> bool:
    """桌宠启动：优先快速拉起窗口；仅 health/对话不可用时重启 API。"""
    if is_api_ready_for_pet(timeout=2.0):
        if not is_api_operational(timeout=2.0):
            logger.info(
                "API 可对话但未完全就绪（TTS/MCP 版本或预热），桌宠先启动，后台继续加载"
            )
        return True

    port_busy = bool(_pids_on_port(API_PORT))
    if port_busy:
        logger.info("端口 %s 已有进程，等待其响应（最多 20s）…", API_PORT)
        if wait_for_api_pet_ready(timeout=min(20.0, timeout * 0.35)):
            return True
        logger.warning("端口 %s 占用但 API 未就绪，正在结束僵死进程…", API_PORT)
        kill_api_on_port()
        time.sleep(1.0)
    elif is_api_alive(timeout=1.5) and not is_chat_api_ready(timeout=1.5):
        logger.warning("API(8765) health 正常但对话模块异常，正在重启…")
        kill_api_on_port()
        time.sleep(0.5)

    proc = start_api_subprocess()
    ok = wait_for_api_pet_ready(timeout=timeout)
    if not ok:
        try:
            proc.terminate()
        except Exception:
            pass
    return ok


def ensure_api_operational(*, timeout: float = 60.0) -> bool:
    """设置页/MCP 等需要完整 API 能力时：不可用或版本过旧时拉起/重启子进程。"""
    if is_api_operational(timeout=2.0):
        return True
    if is_api_alive() or _pids_on_port(API_PORT):
        if is_chat_api_ready(timeout=2.0) and not chat_api_version_ok(timeout=2.0):
            logger.warning(
                "API(8765) 版本过旧（stream_sse_version<%s），正在重启…",
                MIN_STREAM_SSE_VERSION,
            )
        elif is_chat_api_ready(timeout=2.0) and not tts_api_version_ok(timeout=2.0):
            logger.warning(
                "API(8765) TTS 模块过旧（service_version<%s），正在重启…",
                MIN_TTS_SERVICE_VERSION,
            )
        else:
            logger.warning("检测到 API(8765) 异常或正在关闭，正在重启…")
        kill_api_on_port()
        time.sleep(0.5)
    proc = start_api_subprocess()
    ok = wait_for_api_operational(timeout=timeout)
    if not ok:
        try:
            proc.terminate()
        except Exception:
            pass
    return ok
