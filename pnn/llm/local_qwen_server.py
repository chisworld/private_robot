"""本地 Qwen llama-server：路径解析、后台启动（桌宠一键拉起）。"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from pnn.core.paths import (
    PROJECT_ROOT,
    QWEN_LOCAL_BUNDLE_DIR,
    QWEN_LOCAL_DEFAULT_ALIAS,
    QWEN_LOCAL_DEFAULT_PORT,
)

logger = logging.getLogger(__name__)

DEFAULT_CTX = 8192
DEFAULT_NGL = 99
_LOG_PATH = PROJECT_ROOT / "data" / "logs" / "qwen_boot.log"
_prelaunch_attempted = False


def _port_in_use(port: int) -> bool:
    import subprocess as sp

    try:
        out = sp.check_output(
            ["netstat", "-ano"],
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except (sp.CalledProcessError, FileNotFoundError):
        return False
    needle = f":{port}"
    for line in out.splitlines():
        if "LISTENING" in line.upper() and needle in line:
            return True
    return False


def find_bundle(explicit: str | Path | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Qwen bundle not found: {path}")
        return path
    if QWEN_LOCAL_BUNDLE_DIR.is_dir():
        return QWEN_LOCAL_BUNDLE_DIR
    matches = sorted(PROJECT_ROOT.glob("models/Qwen*/llama-server.exe"))
    if len(matches) == 1:
        return matches[0].parent
    if not matches:
        raise FileNotFoundError(f"Qwen bundle not found: {QWEN_LOCAL_BUNDLE_DIR}")
    dirs = ", ".join(p.parent.name for p in matches)
    raise FileNotFoundError(f"Multiple Qwen bundles under models/: {dirs}")


def resolve_gguf(models_dir: Path) -> tuple[Path, Path | None]:
    if not models_dir.is_dir():
        raise FileNotFoundError(f"Models folder missing: {models_dir}")
    all_gguf = sorted(models_dir.glob("*.gguf"))
    main = [p for p in all_gguf if not p.name.lower().startswith("mmproj")]
    mmproj = next((p for p in all_gguf if p.name.lower().startswith("mmproj")), None)
    if not main:
        raise FileNotFoundError(f"No main .gguf in {models_dir}")
    if len(main) > 1:
        names = ", ".join(p.name for p in main)
        raise FileNotFoundError(f"Multiple main .gguf files: {names}")
    return main[0], mmproj


def build_llama_server_cmd(
    *,
    bundle: Path | None = None,
    port: int = QWEN_LOCAL_DEFAULT_PORT,
    alias: str = QWEN_LOCAL_DEFAULT_ALIAS,
    ctx: int = DEFAULT_CTX,
    ngl: int = DEFAULT_NGL,
    vision_local: bool = False,
) -> tuple[list[str], Path, Path]:
    root = bundle or find_bundle()
    server = root / "llama-server.exe"
    if not server.is_file():
        raise FileNotFoundError(f"llama-server.exe missing: {server}")
    model_path, mmproj_path = resolve_gguf(root / "Models")
    cmd = [
        str(server),
        "-m",
        str(model_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "-ngl",
        str(ngl),
        "-c",
        str(ctx),
        "--alias",
        alias,
        "--flash-attn",
        "on",
        "--jinja",
        "--reasoning-budget",
        "0",
    ]
    if vision_local:
        if mmproj_path is None:
            raise FileNotFoundError("mmproj*.gguf not found for --vision-local")
        cmd.extend(["--mmproj", str(mmproj_path)])
    return cmd, root, model_path


def sync_local_qwen_config(
    port: int = QWEN_LOCAL_DEFAULT_PORT,
    alias: str = QWEN_LOCAL_DEFAULT_ALIAS,
) -> None:
    from pnn.core.env import load_env, upsert_env
    from pnn.llm.config_store import load_llm_config, save_llm_config

    load_env(force=True)
    upsert_env("LOCAL_LLM_BASE_URL", f"http://127.0.0.1:{port}")
    upsert_env("LOCAL_LLM_MODEL", alias)
    upsert_env("LOCAL_LLM_API_KEY", "local")
    cfg = load_llm_config()
    cfg.local_model_base_url = f"http://127.0.0.1:{port}"
    cfg.local_model = alias
    cfg.local_model_api_key = "local"
    save_llm_config(cfg, keep_api_key=True)


def is_local_qwen_running(
    base_url: str | None = None,
    *,
    timeout: float = 2.0,
) -> bool:
    from pnn.llm.local_qwen import local_llm_health

    url = (base_url or f"http://127.0.0.1:{QWEN_LOCAL_DEFAULT_PORT}").strip()
    ok, _ = local_llm_health(url)
    return ok


def start_local_qwen_subprocess(
    *,
    port: int = QWEN_LOCAL_DEFAULT_PORT,
    alias: str = QWEN_LOCAL_DEFAULT_ALIAS,
    ctx: int = DEFAULT_CTX,
    ngl: int = DEFAULT_NGL,
    vision_local: bool = False,
) -> subprocess.Popen | None:
    """后台启动 llama-server；已在线则返回 None。"""
    base_url = f"http://127.0.0.1:{port}"
    if is_local_qwen_running(base_url):
        logger.info("本地 Qwen 已在运行: %s", base_url)
        return None
    if _port_in_use(port):
        logger.info("端口 %s 已被占用，假定 llama-server 正在加载", port)
        return None

    cmd, bundle_cwd, model_path = build_llama_server_cmd(
        port=port,
        alias=alias,
        ctx=ctx,
        ngl=ngl,
        vision_local=vision_local,
    )
    sync_local_qwen_config(port, alias)

    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(_LOG_PATH, "a", encoding="utf-8")
    log_file.write(
        f"\n--- llama-server start {time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"model={model_path.name} port={port} ---\n"
    )
    log_file.flush()
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        cmd,
        cwd=str(bundle_cwd),
        creationflags=flags,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    logger.info(
        "已后台启动 llama-server (pid=%s) → %s model=%s",
        proc.pid,
        base_url,
        alias,
    )
    return proc


def prelaunch_local_qwen_for_pet(*, quiet: bool = False) -> bool:
    """桌宠启动时调用：若已安装 Qwen 整合包则后台拉起 llama-server（不阻塞 UI）。"""
    global _prelaunch_attempted
    from pnn.llm.local_qwen import bundle_installed

    if not bundle_installed():
        return False
    if _prelaunch_attempted:
        return True
    _prelaunch_attempted = True
    try:
        from pnn.llm.config_store import load_llm_config

        cfg = load_llm_config()
        port = QWEN_LOCAL_DEFAULT_PORT
        base = (cfg.local_model_base_url or "").strip().rstrip("/")
        if base.endswith(":8080") or ":808" in base:
            try:
                port = int(base.rsplit(":", 1)[-1])
            except ValueError:
                port = QWEN_LOCAL_DEFAULT_PORT
        alias = (cfg.local_model or QWEN_LOCAL_DEFAULT_ALIAS).strip() or QWEN_LOCAL_DEFAULT_ALIAS

        if is_local_qwen_running(f"http://127.0.0.1:{port}"):
            if not quiet:
                print("[pet] 本地 Qwen 已在线", flush=True)
            return True

        start_local_qwen_subprocess(port=port, alias=alias)
        if not quiet:
            print(
                "[pet] 本地 Qwen 已在后台加载（角色页开启 NSFW 后用于日常闲聊；"
                "首次加载需数分钟，日志 data/logs/qwen_boot.log）",
                flush=True,
            )
        return True
    except Exception as exc:
        logger.warning("本地 Qwen 预启动失败: %s", exc)
        if not quiet:
            print(f"[pet] 本地 Qwen 预启动失败: {exc}", flush=True)
        return False
