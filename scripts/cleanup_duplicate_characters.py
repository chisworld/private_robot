"""删除已废弃角色目录（小倪、理想奈），仅保留里想奈。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEEP = "里想奈"
REMOVE_IDS = ("小倪", "理想奈")


def _rmtree(rel: str) -> None:
    p = ROOT / rel
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
        print("removed dir", rel)
    elif p.is_file():
        p.unlink(missing_ok=True)
        print("removed file", rel)


def main() -> None:
    for cid in REMOVE_IDS:
        for base in (
            f"data/characters/{cid}",
            f"data/memory/{cid}",
            f"data/tts/{cid}",
            f"data/assets/time_greetings/{cid}",
            f"models/{cid}",
            f"live2d/{cid}",
            f"data/config/{cid}.json",
        ):
            _rmtree(base)

    llm = ROOT / "data/config/llm.json"
    if llm.is_file():
        data = json.loads(llm.read_text(encoding="utf-8"))
        if data.get("active_character") in REMOVE_IDS:
            data["active_character"] = KEEP
            llm.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("llm active_character ->", KEEP)

    print("保留角色:", KEEP)
    print("完成。请重启 API 与桌宠。")


if __name__ == "__main__":
    main()
