"""项目结构摘要：供 Agent 改代码时定位文件。"""

from __future__ import annotations

from pathlib import Path

from pnn.core.paths import (
    APPS_DIR,
    DATA_DIR,
    PNN_PKG_DIR,
    PROJECT_ROOT,
    SCRIPTS_DIR,
    SERVER_DIR,
)

# 改代码时优先关注的目录（相对项目根）
_CODE_ROOTS: tuple[tuple[str, Path, str], ...] = (
    ("pnn/", PNN_PKG_DIR, "桌宠/ASR/TTS/LLM/MCP/Agent 核心"),
    ("server/", SERVER_DIR, "FastAPI 网关 8765"),
    ("apps/", APPS_DIR, "Next.js 前端"),
    ("scripts/", SCRIPTS_DIR, "启动与工具脚本"),
    ("data/config/", DATA_DIR / "config", "业务配置 JSON"),
    ("config/templates/", PROJECT_ROOT / "config" / "templates", "配置模板"),
)


def _list_py_modules(root: Path, *, limit: int = 12) -> list[str]:
    if not root.is_dir():
        return []
    out: list[str] = []
    for p in sorted(root.rglob("*.py")):
        if any(part.startswith(".") or part in ("__pycache__", "node_modules") for part in p.parts):
            continue
        try:
            rel = p.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            continue
        out.append(rel)
        if len(out) >= limit:
            break
    return out


def build_project_map(*, max_files_per_root: int = 8) -> str:
    """生成紧凑项目地图，注入 Agent 系统提示。"""
    lines = ["【项目结构速览】"]
    for label, path, desc in _CODE_ROOTS:
        lines.append(f"• {label} — {desc}")
        samples = _list_py_modules(path, limit=max_files_per_root)
        if samples:
            lines.append("  示例: " + ", ".join(samples))
    lines.append(
        f"• 根目录: {PROJECT_ROOT.resolve().as_posix()}；"
        "改代码前用 search_files / list_directory 定位，勿猜测路径。"
    )
    return "\n".join(lines)
