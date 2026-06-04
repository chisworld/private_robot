"""理想奈 → 里想奈：补全配置与记忆（目录已部分重命名时使用）。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD, NEW = "理想奈", "里想奈"


def rep_file(p: Path) -> None:
    if not p.is_file():
        return
    t = p.read_text(encoding="utf-8")
    if OLD not in t:
        return
    p.write_text(t.replace(OLD, NEW), encoding="utf-8")
    print("ok", p.relative_to(ROOT))


def main() -> None:
    for rel in (
        "data/config/llm.json",
        "data/config/tts.json",
        "data/config/pet_ui.json",
        f"data/config/{NEW}.json",
        f"data/characters/{NEW}/voice_emotions.json",
    ):
        rep_file(ROOT / rel)

    old_cfg = ROOT / f"data/config/{OLD}.json"
    new_cfg = ROOT / f"data/config/{NEW}.json"
    if old_cfg.is_file() and not new_cfg.is_file():
        old_cfg.rename(new_cfg)
        rep_file(new_cfg)
    elif old_cfg.is_file():
        old_cfg.unlink()

    dst = ROOT / "data/memory" / NEW
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "memories.json").write_text(
        json.dumps({"character_id": NEW, "items": []}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (dst / "state.json").write_text(
        json.dumps({"affection": 80, "mood": "neutral"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    chroma = dst / "chroma"
    if chroma.is_dir():
        shutil.rmtree(chroma)
    print("memory cleared:", dst.relative_to(ROOT))

    src_mem = ROOT / "data/memory" / OLD
    if src_mem.is_dir() and src_mem != dst:
        shutil.rmtree(src_mem, ignore_errors=True)

    dup = ROOT / "data/characters" / OLD
    if dup.is_dir() and (ROOT / "data/characters" / NEW).is_dir():
        shutil.rmtree(dup, ignore_errors=True)
        print("removed", dup.relative_to(ROOT))


if __name__ == "__main__":
    main()
