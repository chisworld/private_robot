#!/usr/bin/env python3
"""按角色预生成全部时段问候 wav（早/中/晚 × 中/日）→ data/assets/time_greetings/{角色ID}/。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from pnn.pet.api_client import PetApiClient
    from pnn.pet.time_greeting import (
        ALL_GREETING_LANGS,
        ALL_GREETING_SLOTS,
        list_time_greeting_character_ids,
        migrate_flat_assets_to_character,
        regenerate_all_time_greeting_wavs,
    )

    migrated = migrate_flat_assets_to_character()
    if migrated:
        print(f"已将根目录 {migrated} 个问候文件迁入 塞拉/")

    api = PetApiClient()
    if not api.health():
        print("API 未运行，请先启动 8765 服务（如 启动桌宠.bat）", file=sys.stderr)
        return 1
    print("等待 TTS 就绪…")
    if not api.ensure_tts_ready(timeout=180):
        print("TTS 未就绪", file=sys.stderr)
        return 1

    chars = list_time_greeting_character_ids()
    n = len(chars) * len(ALL_GREETING_SLOTS) * len(ALL_GREETING_LANGS)
    print(f"开始合成 {n} 条问候语音（角色: {', '.join(chars)}）…")
    paths = regenerate_all_time_greeting_wavs(api)
    for cid in chars:
        for slot in ALL_GREETING_SLOTS:
            for lang in ALL_GREETING_LANGS:
                path = paths[f"{cid}/{slot}_{lang}"]
                size = path.stat().st_size if path.is_file() else 0
                print(f"  [{cid}/{slot}/{lang}] {path} ({size} 字节)")
    from pnn.pet.common_phrases import (
        ALL_COMMON_PHRASE_IDS,
        ALL_COMMON_PHRASE_LANGS,
        regenerate_all_common_phrase_wavs,
    )

    print("开始合成常用句缓存…")
    phrase_paths = regenerate_all_common_phrase_wavs(api, character_ids=chars)
    for cid in chars:
        for pid in ALL_COMMON_PHRASE_IDS:
            for lang in ALL_COMMON_PHRASE_LANGS:
                path = phrase_paths[f"{cid}/{pid}_{lang}"]
                size = path.stat().st_size if path.is_file() else 0
                print(f"  [{cid}/{pid}/{lang}] {path} ({size} 字节)")
    print("完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
