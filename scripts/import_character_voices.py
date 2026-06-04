#!/usr/bin/env python3
"""从 models/{角色ID}/ 导入 [情绪标签]参考文本.wav 与权重，写入角色包与 TTS 多标签参考音。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    import argparse

    from pnn.characters.pack import load_pack, save_pack
    from pnn.tts.character_layout import normalize_tts_pack_settings, relative_ref_audio_path
    from pnn.tts.voice_library import import_voice_library

    parser = argparse.ArgumentParser(description="导入角色语音库")
    parser.add_argument("character_id", nargs="?", default="里想奈")
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="源目录，默认 models/{角色ID}/",
    )
    args = parser.parse_args()
    cid = args.character_id.strip()

    manifest = import_voice_library(cid, args.source)
    pack = load_pack(cid)
    if pack is None:
        from pnn.characters.pack import CharacterPack

        pack = CharacterPack(id=cid, name=cid)

    pack.tts.gpt_model_path = manifest.gpt_model_path
    pack.tts.sovits_model_path = manifest.sovits_model_path
    default = next(
        (p for p in manifest.presets if p["id"] == manifest.default_emotion_id),
        manifest.presets[0],
    )
    pack.tts.ref_audio_path = default.get("ref_audio_path") or relative_ref_audio_path(cid)
    pack.tts.prompt_text = default.get("prompt_text", "")
    pack.tts.prompt_lang = "ja"
    pack.tts.text_lang = "ja"
    pack.tts = normalize_tts_pack_settings(pack.tts, cid)
    save_pack(pack)

    print(f"已导入角色「{cid}」语音库:")
    print(f"  源目录: {manifest.source_dir}")
    print(f"  参考音: {len(manifest.presets)} 个情绪标签")
    for p in manifest.presets:
        snippet = (p.get("prompt_text") or "")[:40]
        suffix = "…" if len(p.get("prompt_text") or "") > 40 else ""
        print(f"    [{p['id']}] {p['label']}: {snippet}{suffix}")
    print(f"  GPT: {manifest.gpt_model_path}")
    print(f"  SoVITS: {manifest.sovits_model_path}")
    print(f"  清单: data/characters/{cid}/voice_emotions.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
