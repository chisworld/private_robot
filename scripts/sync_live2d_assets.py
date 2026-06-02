# -*- coding: utf-8 -*-
"""将 live2d/14酱 模型资源同步到 Next.js public 目录（供 /pet 与 Live2D 使用）。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pnn.core.paths import live2d_model_dir

SRC = live2d_model_dir()
DST = ROOT / "apps" / "web" / "public" / "live2d" / "models" / "14酱"


def sync() -> int:
    if not SRC.is_dir():
        print(f"[sync_live2d] 源目录不存在: {SRC}", file=sys.stderr)
        return 1

    DST.mkdir(parents=True, exist_ok=True)

    copied = 0
    for path in SRC.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(SRC)
        # 仅同步运行时必需资源，跳过 vtube / 说明等
        suffix = path.suffix.lower()
        if suffix in {".vtube.json", ".xyplugin.json", ".txt"}:
            continue
        if path.name == "icon.png":
            continue
        target = DST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or path.stat().st_mtime > target.stat().st_mtime:
            shutil.copy2(path, target)
            copied += 1

    moc = DST / "我也要死吗.moc3"
    tex0 = DST / "我也要死吗.2048" / "texture_00.png"
    if not moc.is_file() or not tex0.is_file():
        print(
            "[sync_live2d] 同步后仍缺少关键文件（moc3 / texture），请检查 14酱 目录是否完整。",
            file=sys.stderr,
        )
        return 1

    print(f"[sync_live2d] 完成，更新 {copied} 个文件 → {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(sync())
