"""Agent Skills：可复用的任务说明（类似 OpenClaw SKILL.md，注入系统提示）。"""

from __future__ import annotations

import logging
from pathlib import Path

from pnn.core.paths import DATA_DIR

logger = logging.getLogger(__name__)

_BUNDLED_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
_USER_SKILLS_DIR = DATA_DIR / "skills"


def _read_skill_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("读取 Skill 失败 %s: %s", path, exc)
        return ""
    return text


def _collect_skill_paths() -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = path.resolve().as_posix()
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    if _BUNDLED_SKILLS_DIR.is_dir():
        for p in sorted(_BUNDLED_SKILLS_DIR.glob("*.md")):
            add(p)
        for p in sorted(_BUNDLED_SKILLS_DIR.rglob("SKILL.md")):
            add(p)

    if _USER_SKILLS_DIR.is_dir():
        for p in sorted(_USER_SKILLS_DIR.glob("*.md")):
            add(p)
        for p in sorted(_USER_SKILLS_DIR.rglob("SKILL.md")):
            add(p)

    return paths


def load_agent_skills_text(*, code_edit_only: bool = False) -> str:
    """
    加载内置 + data/skills/ 下的 Skill 文本。
    code_edit_only=True 时仅加载文件名含 edit/code/python 的 Skill。
    """
    parts: list[str] = []
    for path in _collect_skill_paths():
        name = path.stem.lower()
        if code_edit_only and not any(k in name for k in ("edit", "code", "python", "skill")):
            if path.name.upper() != "SKILL.MD":
                continue
            parent = path.parent.name.lower()
            if not any(k in parent for k in ("edit", "code", "python")):
                continue
        body = _read_skill_file(path)
        if not body:
            continue
        label = path.stem if path.name.lower() != "skill.md" else path.parent.name
        parts.append(f"### Skill: {label}\n{body}")
    if not parts:
        return ""
    return "【Agent Skills — 按以下规程执行】\n\n" + "\n\n".join(parts)


def ensure_user_skills_dir() -> Path:
    _USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    readme = _USER_SKILLS_DIR / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# 自定义 Agent Skills\n\n"
            "在本目录放置 `.md` 或 `*/SKILL.md`，重启 API 后会在 Agent 改代码时注入。\n\n"
            "示例：\n\n"
            "```\n"
            "data/skills/my_api_edit.md\n"
            "data/skills/refactor/SKILL.md\n"
            "```\n",
            encoding="utf-8",
        )
    return _USER_SKILLS_DIR
