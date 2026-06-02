"""Windows 原生文件/文件夹选择对话框（tkinter 子进程）。"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_PICKER_SCRIPT = r"""
import json
import sys
from pathlib import Path
from tkinter import Tk, filedialog

payload = json.loads(sys.stdin.read())
root = Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()

initial = payload.get("initial_dir") or ""
if initial:
    p = Path(initial)
    if p.is_file():
        initial = str(p.parent)
    elif not p.is_dir():
        initial = ""

mode = payload.get("mode", "file")
title = payload.get("title") or "选择"
path = ""
if mode == "folder":
    path = filedialog.askdirectory(title=title, initialdir=initial or None) or ""
else:
    filetypes = payload.get("filetypes") or [("All files", "*.*")]
    path = filedialog.askopenfilename(title=title, initialdir=initial or None, filetypes=filetypes) or ""
root.destroy()
print(json.dumps({"path": path}, ensure_ascii=False))
"""


def _run_picker(payload: dict) -> str | None:
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PICKER_SCRIPT],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        logger.warning("文件选择对话框超时")
        return None
    except Exception as exc:
        logger.warning("文件选择对话框失败: %s", exc)
        return None

    if proc.returncode != 0:
        logger.warning("picker stderr: %s", proc.stderr[-500:] if proc.stderr else "")
        return None

    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return None
    try:
        data = json.loads(line[-1])
    except json.JSONDecodeError:
        return None
    path = str(data.get("path") or "").strip()
    return path or None


def pick_file(
    *,
    title: str = "选择文件",
    filetypes: list[tuple[str, str]] | None = None,
    initial_dir: str | None = None,
) -> str | None:
    return _run_picker(
        {
            "mode": "file",
            "title": title,
            "filetypes": filetypes or [("All files", "*.*")],
            "initial_dir": initial_dir or "",
        }
    )


def pick_folder(*, title: str = "选择文件夹", initial_dir: str | None = None) -> str | None:
    return _run_picker({"mode": "folder", "title": title, "initial_dir": initial_dir or ""})
