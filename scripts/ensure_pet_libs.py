# -*- coding: utf-8 -*-
"""确保桌宠所需的 Pixi / Live2D 脚本在 public/live2d/libs 中（离线可用）。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / "apps" / "web" / "public" / "live2d" / "libs"
NODE_PIXI = ROOT / "apps" / "web" / "node_modules" / "pixi.js" / "dist" / "browser" / "pixi.min.js"
NODE_L2D = ROOT / "apps" / "web" / "node_modules" / "pixi-live2d-display" / "dist" / "index.min.js"


def ensure() -> int:
    LIBS.mkdir(parents=True, exist_ok=True)
    cubism = LIBS / "live2dcubismcore.min.js"
    if not cubism.is_file():
        print(f"[ensure_pet_libs] 缺少 {cubism}", file=sys.stderr)
        return 1

    if not NODE_PIXI.is_file() or not NODE_L2D.is_file():
        print(
            "[ensure_pet_libs] 请先在 apps/web 执行: "
            "npm install pixi.js@6.5.8 pixi-live2d-display@0.4.0",
            file=sys.stderr,
        )
        return 1

    shutil.copy2(NODE_PIXI, LIBS / "pixi.min.js")
    shutil.copy2(NODE_L2D, LIBS / "pixi-live2d-display.min.js")
    print(f"[ensure_pet_libs] 已更新 Pixi 库 → {LIBS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(ensure())
