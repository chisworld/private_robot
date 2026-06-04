"""一次性迁移：小倪 → 理想奈（目录重命名、记忆清零、配置路径更新）。"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_ID = "小倪"
NEW_ID = "理想奈"


def _rename_dir(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    if dst.exists():
        raise SystemExit(f"目标已存在，中止: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    print(f"重命名: {src.relative_to(ROOT)} → {dst.relative_to(ROOT)}")


def _replace_in_json_file(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if OLD_ID not in text:
        return
    path.write_text(text.replace(OLD_ID, NEW_ID), encoding="utf-8")
    print(f"更新文本: {path.relative_to(ROOT)}")


def _reset_memory(char_dir: Path) -> None:
    if char_dir.is_dir():
        shutil.rmtree(char_dir)
    char_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    (char_dir / "memories.json").write_text(
        json.dumps({"character_id": NEW_ID, "items": []}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (char_dir / "state.json").write_text(
        json.dumps(
            {
                "affection": 80,
                "mood": "neutral",
                "last_decay": now,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"记忆已清零: {char_dir.relative_to(ROOT)}")


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
    ]
    for src, dst in renames:
        _rename_dir(src, dst)

    old_mem = ROOT / "data" / "memory" / OLD_ID
    new_mem = ROOT / "data" / "memory" / NEW_ID
    if old_mem.is_dir() and old_mem != new_mem:
        shutil.rmtree(old_mem)
    _reset_memory(new_mem)

    cfg_old = ROOT / "data" / "config" / f"{OLD_ID}.json"
    cfg_new = ROOT / "data" / "config" / f"{NEW_ID}.json"
    if cfg_old.is_file():
        if cfg_new.is_file():
            cfg_old.unlink()
        else:
            cfg_old.rename(cfg_new)
        _replace_in_json_file(cfg_new)

    for rel in (
        "data/config/llm.json",
        "data/config/tts.json",
        "data/config/pet_ui.json",
        f"data/characters/{NEW_ID}/pack.json",
        f"data/characters/{NEW_ID}/voice_emotions.json",
    ):
        _replace_in_json_file(ROOT / rel)

    print("完成。请重启 API 与桌宠。")


if __name__ == "__main__":
    main()
