"""仅启动桌宠窗口（需 API 8765 已在运行）。用法: python scripts/run_pet.py"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

API_HEALTH = "http://127.0.0.1:8765/api/health"


def _api_ok() -> bool:
    try:
        with urllib.request.urlopen(API_HEALTH, timeout=1) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def main() -> None:
    if not _api_ok():
        print(
            "[pet] API 8765 未就绪，仍将打开桌宠窗口（对话需稍后启动 API）。",
            flush=True,
        )
    else:
        print("[pet] API 已就绪，快速启动桌宠…", flush=True)

    from pnn.core.audio_cache import prune_audio_cache

    prune_audio_cache()
    from pnn.pet.app import main as pet_main

    pet_main()


if __name__ == "__main__":
    main()
