"""项目根目录 .env 加载（密钥与运行参数，勿提交 .env 到 Git）。"""

from __future__ import annotations

import os
from pathlib import Path

from pnn.core.paths import PROJECT_ROOT

_loaded = False
_env_file: Path | None = None


def load_env(*, force: bool = False) -> Path | None:
    """从项目根读取 `.env`；已加载则跳过（除非 force=True）。"""
    global _loaded, _env_file
    if _loaded and not force:
        return _env_file

    path = PROJECT_ROOT / ".env"
    _env_file = path if path.is_file() else None

    try:
        from dotenv import load_dotenv
    except ImportError:
        if _env_file is not None:
            _load_env_manual(_env_file)
        _loaded = True
        return _env_file

    if _env_file is not None:
        load_dotenv(_env_file, override=False)
    _loaded = True
    return _env_file


def _load_env_manual(path: Path) -> None:
    """无 python-dotenv 时的简易解析（KEY=VALUE，忽略 # 注释）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def getenv(key: str, default: str = "") -> str:
    load_env()
    return os.getenv(key, default).strip()


def env_file_path() -> Path | None:
    load_env()
    return _env_file


def upsert_env(key: str, value: str) -> Path:
    """写入或更新 .env 中的单项（保存设置里的 API Key 时使用）。"""
    path = PROJECT_ROOT / ".env"
    key = key.strip()
    line = f"{key}={value.strip()}\n"
    lines: list[str] = []
    found = False
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip() or raw.strip().startswith("#"):
                lines.append(raw)
                continue
            k, _, _ = raw.partition("=")
            if k.strip() == key:
                lines.append(line.rstrip("\n"))
                found = True
            else:
                lines.append(raw)
    if not found:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(line.rstrip("\n"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    global _loaded
    _loaded = False
    load_env(force=True)
    os.environ[key] = value.strip()
    return path
