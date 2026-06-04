#!/usr/bin/env python3
"""将 TTS 参考音 / prompt / pack.json 路径迁移为按角色分目录。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from pnn.tts.character_layout import migrate_legacy_tts_assets, refresh_all_pack_tts_paths

    stats = migrate_legacy_tts_assets()
    packs = refresh_all_pack_tts_paths()
    print("TTS 按角色迁移完成:")
    print(f"  参考音: {stats.get('refs', 0)}")
    print(f"  角色包: {packs}")
    print(f"  截图提示: {stats.get('screenshot_hints', 0)}")
    print("目录示例: data/tts/{角色ID}/reference.wav, prompt.txt, output/")
    print("模型权重: models/character/{角色ID}/{角色ID}.ckpt|.pth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
