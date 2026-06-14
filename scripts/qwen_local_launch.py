"""Patch .env for local Qwen (llama-server) and start the server."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pnn.core.env import getenv, load_env, upsert_env
from pnn.llm.local_qwen_server import (
    DEFAULT_CTX,
    DEFAULT_NGL,
    build_llama_server_cmd,
    is_local_qwen_running,
    start_local_qwen_subprocess,
    sync_local_qwen_config,
)

DEFAULT_PORT = 8080
DEFAULT_ALIAS = "qwen3.6"
DEFAULT_CLOUD_VL = "qwen-vl-plus"


def _has_cloud_vision_key() -> bool:
    load_env(force=True)
    return bool(
        getenv("DASHSCOPE_API_KEY", "")
        or getenv("VISION_API_KEY", "")
    )


def _ensure_env(port: int, alias: str, *, vision_local: bool) -> None:
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env_path.is_file():
        if not example.is_file():
            raise SystemExit("[ERROR] Missing .env and .env.example")
        shutil.copyfile(example, env_path)
        print("[OK] Created .env from .env.example")
    sync_local_qwen_config(port, alias)
    load_env(force=True)

    if vision_local:
        upsert_env("VISION_BASE_URL", f"http://127.0.0.1:{port}")
        upsert_env("VISION_MODEL", alias)
    elif _has_cloud_vision_key():
        vl = getenv("DASHSCOPE_VL_MODEL", "") or DEFAULT_CLOUD_VL
        if vl == "qwen-vl-max":
            upsert_env("DASHSCOPE_VL_MODEL", DEFAULT_CLOUD_VL)
            vl = DEFAULT_CLOUD_VL
        print(
            f"[OK] 识图走 DashScope 云端 ({vl})；"
            "日常 DeepSeek 对话见 LLM 设置，NSFW 闲聊见角色页开关"
        )
    else:
        print(
            "[WARN] 未配置 DASHSCOPE_API_KEY，粘贴截图识图不可用。"
            "可在 .env 填入 DashScope Key。"
        )

    print(
        f"[OK] 本地 Qwen 服务 -> http://127.0.0.1:{port}  model={alias} "
        "(桌宠角色页开启 NSFW 后用于日常闲聊)"
    )


def _sync_llm_json(port: int, alias: str, *, vision_local: bool) -> None:
    from pnn.llm.config_store import load_llm_config, save_llm_config

    sync_local_qwen_config(port, alias)
    if vision_local:
        cfg = load_llm_config()
        cfg.vision_base_url = f"http://127.0.0.1:{port}"
        cfg.vision_model = alias
        cfg.thinking_enabled = False
        save_llm_config(cfg, keep_api_key=True)
    print(f"[OK] llm.json 已写入 local_model={alias}（不修改 DeepSeek base_url/model）")


def main() -> int:
    parser = argparse.ArgumentParser(description="Start local Qwen llama-server")
    parser.add_argument("--bundle", help="Path to Qwen llama.cpp bundle directory")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--alias", default=DEFAULT_ALIAS, help="OpenAI API model alias")
    parser.add_argument("--ctx", type=int, default=DEFAULT_CTX, help="Context size")
    parser.add_argument("--ngl", type=int, default=DEFAULT_NGL, help="GPU layers (-ngl)")
    parser.add_argument(
        "--vision-local",
        action="store_true",
        help="本地 mmproj 识图（35B+视觉极慢，会拖垮对话，不推荐）",
    )
    parser.add_argument(
        "--vision",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    vision_local = bool(args.vision_local or args.vision)
    if args.vision and not args.vision_local:
        print(
            "[WARN] --vision 已弃用：默认改为「本地对话 + DashScope 云端识图」。"
            "若坚持本地识图请加 --vision-local（很慢）。"
        )

    base_url = f"http://127.0.0.1:{args.port}"
    if is_local_qwen_running(base_url):
        print(f"[WARN] Port {args.port} already responds (llama-server may be running).")
        print("       Stop the other process or use --port to pick another port.")
        return 1

    _ensure_env(args.port, args.alias, vision_local=vision_local)
    _sync_llm_json(args.port, args.alias, vision_local=vision_local)

    cmd, bundle_cwd, model_path = build_llama_server_cmd(
        port=args.port,
        alias=args.alias,
        ctx=args.ctx,
        ngl=args.ngl,
        vision_local=vision_local,
    )
    if vision_local:
        print(
            "[WARN] 已启用本地 mmproj：35B 模型 + 视觉投影会严重拖慢甚至阻塞对话。"
        )

    print()
    print("========================================")
    print("  Local Qwen (llama-server)")
    print("========================================")
    print(f"  Model : {model_path.name}")
    print(f"  Chat  : http://127.0.0.1:{args.port}/v1  ({args.alias})")
    if vision_local:
        print("  Vision: local mmproj")
    elif _has_cloud_vision_key():
        vl = getenv("DASHSCOPE_VL_MODEL", "") or DEFAULT_CLOUD_VL
        print(f"  Vision: DashScope cloud ({vl})")
    else:
        print("  Vision: not configured")
    print()
    print("[TIP] 也可直接双击 启动桌宠.bat，会自动在后台拉起 llama-server")
    print()

    try:
        return subprocess.call(cmd, cwd=str(bundle_cwd))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
