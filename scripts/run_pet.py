"""仅启动桌宠窗口（需 API 8765 已在运行）。用法: python scripts/run_pet.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from pnn.core.api_health import ensure_api_for_pet, is_api_ready_for_pet

    print("[pet] 正在检查 API …", flush=True)
    if is_api_ready_for_pet(timeout=0.8):
        print("[pet] API 已就绪，快速启动桌宠…", flush=True)
    elif ensure_api_for_pet(timeout=90.0):
        print("[pet] API 已启动并就绪", flush=True)
    else:
        print(
            "[pet] API 8765 未就绪，仍将打开桌宠窗口（对话/TTS 需稍后手动启动 API）。",
            flush=True,
        )

    from pnn.core.audio_cache import prune_audio_cache

    prune_audio_cache()
    print("[pet] 正在打开 Live2D 窗口…", flush=True)
    from pnn.pet.app import main as pet_main

    pet_main()


if __name__ == "__main__":
    main()
