"""一次性迁移：理想奈 → 里想奈（目录重命名、配置路径更新，记忆保持空库）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_ID = "理想奈"
NEW_ID = "里想奈"


def _rename_dir(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    if dst.exists():
        raise SystemExit(f"目标已存在，中止: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    print(f"重命名: {src.relative_to(ROOT)} → {dst.relative_to(ROOT)}")


def _replace_in_file(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if OLD_ID not in text:
        return
    path.write_text(text.replace(OLD_ID, NEW_ID), encoding="utf-8")
    print(f"更新: {path.relative_to(ROOT)}")


def main() -> None:
    renames = [
        (ROOT / "data" / "characters" / OLD_ID, ROOT / "data" / "characters" / NEW_ID),
        (ROOT / "data" / "tts" / OLD_ID, ROOT / "data" / "tts" / NEW_ID),
        (
            ROOT / "data" / "assets" / "time_greetings" / OLD_ID,
            ROOT / "data" / "assets" / "time_greetings" / NEW_ID,
        ),
        (ROOT / "models" / OLD_ID, ROOT / "models" / NEW_ID),
        (ROOT / "live2d" / OLD_ID, ROOT / "live2d" / NEW_ID),
        (ROOT / "data" / "memory" / OLD_ID, ROOT / "data" / "memory" / NEW_ID),
    ]
    for src, dst in renames:
        _rename_dir(src, dst)

    cfg_old = ROOT / "data" / "config" / f"{OLD_ID}.json"
    cfg_new = ROOT / "data" / "config" / f"{NEW_ID}.json"
    if cfg_old.is_file():
        if cfg_new.is_file():
            cfg_old.unlink()
        else:
            cfg_old.rename(cfg_new)

    mem = ROOT / "data" / "memory" / NEW_ID / "memories.json"
    if mem.is_file():
        data = json.loads(mem.read_text(encoding="utf-8"))
        data["character_id"] = NEW_ID
        mem.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for rel in (
        "data/config/llm.json",
        "data/config/tts.json",
        "data/config/pet_ui.json",
        f"data/config/{NEW_ID}.json",
        f"data/characters/{NEW_ID}/pack.json",
        f"data/characters/{NEW_ID}/voice_emotions.json",
    ):
        _replace_in_file(ROOT / rel)

    print("完成。请重启 API 与桌宠。")


if __name__ == "__main__":
    main()
