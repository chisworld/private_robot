"""PNN Garden 一键启动：自动拉起 API + Web，并打开浏览器。"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pnn.core.env import load_env

load_env()


FRONTEND_PORT = 3000
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"
from pnn.core.paths import api_base_url

_api_base = api_base_url()
API_PORT = int(_api_base.rsplit(":", 1)[-1])
API_HEALTH_URL = f"{_api_base}/api/health"
TTS_HEALTH_URL = f"{_api_base}/api/tts/health"
TTS_PRELOAD_URL = f"{_api_base}/api/tts/preload"
TTS_START_URL = f"{_api_base}/api/tts/server/start"
WEB_DIR = ROOT / "apps" / "web"
REQUIREMENTS = ROOT / "requirements.txt"

PAGES = {
    "chat": "/chat",
    "asr": "/",
    "tts": "/tts",
    "pet": "/pet",
}


def setup_logging() -> None:
    from pnn.core.logging import setup_logging as _setup

    _setup()


def _urlopen_no_proxy(
    url: str,
    *,
    timeout: float = 5.0,
    method: str = "GET",
    data: bytes | None = None,
):
    proxy = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy)
    request = urllib.request.Request(url, method=method, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    return opener.open(request, timeout=timeout)


CHAT_CONFIG_URL = f"{_api_base}/api/chat/config"
TTS_CONFIG_URL = f"{_api_base}/api/tts/config"
REQUIRED_STREAM_SSE_VERSION = 11
from pnn.tts.service import TTS_SERVICE_VERSION as REQUIRED_TTS_SERVICE_VERSION


def is_api_alive() -> bool:
    try:
        with _urlopen_no_proxy(API_HEALTH_URL, timeout=3) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return code == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def is_chat_api_ready() -> bool:
    try:
        with _urlopen_no_proxy(CHAT_CONFIG_URL, timeout=3) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return code == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def api_serves_pet_static() -> bool:
    """当前 API 是否已挂载 /static（桌宠页与 Pixi 库）。"""
    url = f"{_api_base}/static/live2d/libs/pixi.min.js"
    try:
        with _urlopen_no_proxy(url, timeout=3) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return code == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _pids_listening_on_port(port: int) -> list[int]:
    """Windows: 查找监听指定端口的 PID。"""
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
        if "LISTENING" not in line.upper():
            continue
        if needle not in line:
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


def stop_api_on_port(log: logging.Logger, reason: str) -> bool:
    """结束占用 API 端口的进程。"""
    pids = _pids_listening_on_port(API_PORT)
    if not pids:
        return False
    log.warning(
        "%s，正在结束端口 %s 上的进程: %s",
        reason,
        API_PORT,
        ", ".join(str(p) for p in pids),
    )
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            check=False,
            capture_output=True,
        )
    time.sleep(1.0)
    return True


def stop_frontend_on_port(log: logging.Logger, reason: str) -> bool:
    pids = _pids_listening_on_port(FRONTEND_PORT)
    if not pids:
        return False
    log.warning(
        "%s，正在结束端口 %s 上的进程: %s",
        reason,
        FRONTEND_PORT,
        ", ".join(str(p) for p in pids),
    )
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            check=False,
            capture_output=True,
        )
    time.sleep(1.0)
    return True


def stop_stale_api_on_port(log: logging.Logger) -> bool:
    """结束占用 API 端口但不支持 /api/chat 的旧进程。"""
    if not is_api_alive() or is_chat_api_ready():
        return False
    return stop_api_on_port(log, "检测到旧版 API（无对话模块）")


def chat_api_needs_restart() -> bool:
    """旧进程无流式修复标记时需重启，否则对话只显示一两个字。"""
    if not is_api_alive():
        return False
    if not is_chat_api_ready():
        return True
    try:
        import json

        with _urlopen_no_proxy(CHAT_CONFIG_URL, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return int(data.get("stream_sse_version") or 0) < REQUIRED_STREAM_SSE_VERSION
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return True


def tts_api_needs_restart() -> bool:
    """旧 API 保存 TTS 配置会误杀 9880，需重启加载 service_version>=2。"""
    if not is_api_alive():
        return False
    try:
        import json

        with _urlopen_no_proxy(TTS_CONFIG_URL, timeout=3) as resp:
            if getattr(resp, "status", None) == 404 or resp.getcode() == 404:
                return False
            data = json.loads(resp.read().decode("utf-8"))
        return int(data.get("service_version") or 0) < REQUIRED_TTS_SERVICE_VERSION
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False


def is_frontend_alive() -> bool:
    try:
        with _urlopen_no_proxy(FRONTEND_URL, timeout=3) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return code in (200, 304, 307, 308)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def ensure_command(name: str, install_hint: str) -> None:
    if shutil.which(name):
        return
    raise RuntimeError(f"未找到 {name}。{install_hint}")


_PET_MODULES = (
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("requests", "requests"),
    ("sounddevice", "sounddevice"),
    ("numpy", "numpy"),
    ("PySide6", "PySide6"),
    ("live2d", "live2d-py"),
    ("OpenGL", "PyOpenGL"),
)

_PET_RUNTIME_MODULES = (
    ("requests", "requests"),
    ("sounddevice", "sounddevice"),
    ("numpy", "numpy"),
    ("PySide6", "PySide6"),
    ("live2d", "live2d-py"),
    ("OpenGL", "PyOpenGL"),
)


def ensure_python_deps(
    log: logging.Logger,
    *,
    pet_only: bool = False,
    pet_runtime_only: bool = False,
) -> None:
    if pet_runtime_only:
        checks = _PET_RUNTIME_MODULES
    elif pet_only:
        checks = _PET_MODULES
    else:
        checks = (
            ("fastapi", "fastapi"),
            ("uvicorn", "uvicorn"),
            ("requests", "requests"),
        )
    import importlib.util

    missing: list[str] = []
    for mod, _pip_name in checks:
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    if not missing:
        return
    if not REQUIREMENTS.is_file():
        raise RuntimeError(f"缺少 Python 包 {missing}，且未找到 {REQUIREMENTS}")
    log.info("正在安装 Python 依赖（首次约 1～3 分钟）…")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        cwd=ROOT,
    )
    log.info("Python 依赖已就绪")


def ensure_frontend_deps(log: logging.Logger) -> None:
    if (WEB_DIR / "node_modules").is_dir():
        return
    log.info("正在安装前端依赖 npm install（首次约 2～5 分钟）…")
    subprocess.check_call(["npm", "install"], cwd=WEB_DIR, shell=True)
    log.info("前端依赖已就绪")


def kick_tts_warmup(log: logging.Logger) -> None:
    """非阻塞：请求 API 执行 TTS preload（加载配置 + 后台 GPT-SoVITS）。"""
    try:
        with _urlopen_no_proxy(TTS_HEALTH_URL, timeout=3) as resp:
            import json

            if json.loads(resp.read().decode("utf-8")).get("ok"):
                log.info("TTS 已在运行")
                return
    except Exception:
        pass
    try:
        log.info("正在后台预热 TTS（加载配置并启动 GPT-SoVITS）…")
        _urlopen_no_proxy(TTS_PRELOAD_URL, timeout=8, method="POST", data=b"{}")
    except Exception as exc:
        log.warning("TTS preload 失败，回退 server/start: %s", exc)
        try:
            _urlopen_no_proxy(TTS_START_URL, timeout=8, method="POST", data=b"{}")
        except Exception as exc2:
            log.warning("TTS 预热请求失败（桌宠内会继续尝试）: %s", exc2)


def ensure_tts_booted(log: logging.Logger) -> None:
    kick_tts_warmup(log)


def run_api() -> None:
    from pnn.core.cuda_runtime import setup_cuda_dlls
    from pnn.core.logging import run_uvicorn

    setup_cuda_dlls()
    run_uvicorn("server.main:app", port=API_PORT)


def wait_for_api(timeout: float = 60.0, *, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    step = max(0.05, interval)
    while time.monotonic() < deadline:
        if is_api_alive():
            return True
        time.sleep(step)
    return False


def api_ready_for_native_pet() -> bool:
    """API 已运行且版本满足原生桌宠，可跳过重启与长等待。"""
    from pnn.core.api_health import is_api_ready_for_pet

    if not is_api_ready_for_pet():
        return False
    return not chat_api_needs_restart() and not tts_api_needs_restart()


def wait_for_frontend(timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_frontend_alive():
            return True
        time.sleep(0.5)
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PNN Garden 一键启动")
    parser.add_argument(
        "--page",
        choices=tuple(PAGES),
        default="chat",
        help="启动后打开的页面（默认 chat 语音对话）",
    )
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--no-tts-boot", action="store_true", help="不自动尝试启动 TTS")
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="桌宠模式不后台预热 TTS（首次语音可能较慢）",
    )
    parser.add_argument(
        "--warmup-tts",
        action="store_true",
        help="原生桌宠启动时由 launcher 后台拉起 TTS（默认不拉，加快开屏）",
    )
    parser.add_argument(
        "--pet",
        action="store_true",
        help="启动原生 Live2D 桌宠（live2d-py + PySide6，需 API 8765）",
    )
    parser.add_argument(
        "--pet-web",
        action="store_true",
        help="启动 WebEngine 桌宠（pet-desktop.html，需 Pixi 库）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.chdir(ROOT)
    from pnn.core.env import getenv

    if not getenv("HF_ENDPOINT"):
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    setup_logging()
    log = logging.getLogger("launcher")

    open_url = FRONTEND_URL + PAGES[args.page]

    pet_mode = args.pet or args.pet_web

    log.info("=" * 52)
    if pet_mode:
        log.info("  PNN Garden 桌宠启动")
        log.info("  仅 API 8765 + Live2D，不打开网页 / Next.js")
    else:
        log.info("  PNN Garden 一键启动")
        log.info("  正在拉起 API + 网页，无需单独启动后端")
    log.info("=" * 52)
    pet_fast = args.pet and api_ready_for_native_pet()
    try:
        ensure_command("python", "请安装 Python 3.11+ 并加入 PATH")
        if pet_mode:
            ensure_python_deps(
                log,
                pet_only=not pet_fast,
                pet_runtime_only=pet_fast,
            )
        else:
            ensure_command("npm", "请安装 Node.js LTS：https://nodejs.org/")
            ensure_python_deps(log)
            ensure_frontend_deps(log)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        log.error("%s", exc)
        return 1
    # 缓存 is_api_alive() 结果，避免重复 HTTP 超时（每次 3s）
    _api_alive: bool | None = None

    def _ensure_api_alive() -> bool:
        nonlocal _api_alive
        if _api_alive is None:
            _api_alive = is_api_alive()
        return _api_alive

    if pet_fast:
        log.info("API 已就绪（桌宠快速启动）→ http://127.0.0.1:%s", API_PORT)
    elif (args.pet or args.pet_web) and _ensure_api_alive() and tts_api_needs_restart():
        stop_api_on_port(log, "桌宠需要新版 TTS API（同步路由），正在重启 API")
    elif args.pet_web and _ensure_api_alive():
        stop_api_on_port(log, "桌宠模式重启 API（托管 /static 桌宠与 Live2D 资源）")
    elif args.pet_web and _ensure_api_alive() and not api_serves_pet_static():
        stop_api_on_port(log, "API 缺少 /static 桌宠资源，需重启加载新代码")

    if not pet_fast and _ensure_api_alive():
        stop_stale_api_on_port(log)
        if chat_api_needs_restart():
            stop_api_on_port(log, "检测到旧版 API（流式对话异常，需重启加载新代码）")
        elif tts_api_needs_restart():
            stop_api_on_port(log, "检测到旧版 API（TTS 保存会中断合成，需重启加载新代码）")

    api_proc: subprocess.Popen | None = None
    api_thread: threading.Thread | None = None
    we_started_api = False
    if pet_fast or (
        _ensure_api_alive()
        and is_chat_api_ready()
        and not chat_api_needs_restart()
        and (not args.pet_web or api_serves_pet_static())
    ):
        if not pet_fast:
            log.info("API 已在运行 → http://127.0.0.1:%s", API_PORT)
    elif _ensure_api_alive():
        log.error(
            "端口 %s 仍被旧进程占用且无法自动结束。请任务管理器结束 python.exe 后重试。",
            API_PORT,
        )
        return 1
    else:
        from pnn.core.api_health import ensure_api_for_pet, is_api_ready_for_pet

        if _pids_listening_on_port(API_PORT) and not _ensure_api_alive():
            stop_api_on_port(
                log,
                "端口已占用但 /api/health 无响应（僵死进程）",
            )
        we_started_api = True
        if pet_mode:
            log.info("正在准备 API → http://127.0.0.1:%s", API_PORT)
            if not ensure_api_for_pet(timeout=90.0):
                log.error(
                    "API 在 90s 内未就绪。可先运行 launch\\kill_api_8765.bat，"
                    "或结束占用端口 %s 的 python.exe；启动日志: data\\logs\\api_boot.log",
                    API_PORT,
                )
                return 1
        elif is_api_ready_for_pet():
            log.info("API 已就绪 → http://127.0.0.1:%s", API_PORT)
        else:
            api_thread = threading.Thread(target=run_api, name="pnn-api", daemon=False)
            api_thread.start()
            log.info("正在启动 API → http://127.0.0.1:%s", API_PORT)
            if not wait_for_api(interval=0.1):
                log.error(
                    "API 在 60s 内未就绪。请检查端口 %s 是否被占用，关闭旧进程后重试。",
                    API_PORT,
                )
                return 1
        if not is_chat_api_ready():
            log.error("API 已启动但对话模块不可用，请查看上方报错日志。")
            return 1
        log.info("API 已就绪（含对话模块）")

    if not args.no_tts_boot and not pet_mode:
        ensure_tts_booted(log)

    frontend_proc: subprocess.Popen | None = None
    if args.pet_web:
        try:
            from scripts.sync_live2d_assets import sync as sync_live2d
            from scripts.ensure_pet_libs import ensure as ensure_pet_libs

            if sync_live2d() != 0:
                log.warning("Live2D 模型资源同步未完成。")
            if ensure_pet_libs() != 0:
                log.warning("Pixi 库未就绪，桌宠可能只能显示立绘。")
        except Exception as exc:
            log.warning("桌宠资源准备失败: %s", exc)
        log.info("Web 桌宠：由 API 8765 托管静态页，无需启动 Next.js 3000")
    elif args.pet:
        from pnn.core.paths import live2d_model_dir

        model_dir = live2d_model_dir()
        moc = model_dir / "我也要死吗.moc3"
        if not moc.is_file():
            log.warning("14酱 模型不完整，请确认 %s 含 moc3 与贴图", model_dir)
            log.warning(
                "可设置环境变量 LIVE2D_MODEL_DIR 指向含 model3.json 的目录，"
                "例如 live2d/14酱"
            )
        log.info("原生桌宠：加载模型 %s", model_dir)
    elif is_frontend_alive():
        log.info("前端已在运行 → %s", FRONTEND_URL)
    else:
        log.info("正在启动网页 → %s", FRONTEND_URL)
        frontend_proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=WEB_DIR,
            shell=True,
        )
        if not wait_for_frontend(120.0):
            log.error("前端在 120s 内未就绪，请查看上方报错。")
            if frontend_proc:
                frontend_proc.terminate()
            return 1
        log.info("前端已就绪")

    if pet_mode:
        should_warm_tts = (
            not args.no_warmup
            and not args.no_tts_boot
            and (args.pet_web or args.warmup_tts)
        )
        if should_warm_tts:
            threading.Thread(
                target=kick_tts_warmup,
                args=(log,),
                name="tts-warmup",
                daemon=True,
            ).start()

        if args.pet_web:
            log.info("正在启动 Web 桌宠 → http://127.0.0.1:%s/static/pet-desktop.html", API_PORT)
            log.info("-" * 52)
            log.info("  Web 桌宠（PySide6 WebEngine）")
            log.info("  · 拖拽移动 · Ctrl+M 语音（网页内）")
            log.info("-" * 52)
            from scripts.pet_window import main as pet_main

            pet_main()
        else:
            log.info("正在启动原生 Live2D 桌宠（窗口先显示，TTS 后台预热）…")
            log.info("-" * 52)
            log.info("  人物窗 + 对话窗 · Ctrl+M 语音")
            log.info("  TTS 在后台加载，对话窗会提示「TTS 已就绪」")
            log.info("-" * 52)
            from pnn.pet.app import main as pet_native_main

            pet_native_main()

        if frontend_proc:
            frontend_proc.terminate()
        return 0

    if not args.no_browser:
        webbrowser.open(open_url)
        log.info("已打开浏览器: %s", open_url)

    log.info("-" * 52)
    log.info("  使用说明")
    log.info("  · 关闭本窗口 = 停止本次启动的前端与 API")
    log.info("  · 语音对话: %s/chat", FRONTEND_URL)
    log.info("  · 语音识别: %s/", FRONTEND_URL)
    log.info("  · 语音合成: %s/tts", FRONTEND_URL)
    log.info("  · 原生桌宠: python scripts\\launcher.py --pet")
    log.info("  · Web 桌宠: python scripts\\launcher.py --pet-web")
    log.info("  · 仅 API 调试: python -m server.main")
    log.info("-" * 52)

    if frontend_proc is None:
        if we_started_api and api_thread is not None:
            log.info("前端已在其它窗口运行；本窗口保持打开以维持 API，按 Ctrl+C 退出。")
            try:
                api_thread.join()
            except KeyboardInterrupt:
                log.info("正在关闭 API…")
            return 0
        log.info("服务已在运行，可直接使用浏览器访问。")
        return 0

    try:
        if we_started_api and api_thread is not None:
            # 前端结束时一并结束 API 进程
            code = frontend_proc.wait()
            return code
        return frontend_proc.wait()
    except KeyboardInterrupt:
        log.info("正在关闭…")
        frontend_proc.terminate()
        try:
            frontend_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            frontend_proc.kill()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
