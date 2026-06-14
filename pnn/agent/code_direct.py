"""代码路径直达：用户给出白名单内文件时预读内容，避免模型口头拒绝。"""

from __future__ import annotations

import re
from pathlib import Path

_MAX_PREVIEW_CHARS = 12000
_MAX_FILES = 3

_READ_INTENT_RE = re.compile(
    r"(?:读|看|打开|查看|瞧瞧|浏览|显示|展示)"
    r"(?:一下|下|读|读读)?",
    re.IGNORECASE,
)
_EDIT_INTENT_RE = re.compile(r"(?:改|修|写|删|创建|编辑|实现|修复|重构)", re.IGNORECASE)


def _looks_like_file_path(path: Path) -> bool:
    if path.suffix:
        return True
    try:
        return path.is_file()
    except OSError:
        return False


def _workspace_file_candidates(user_message: str) -> list[Path]:
    from pnn.mcp.code_workspace import extract_paths_from_text, is_path_in_workspace

    candidates: list[Path] = []
    seen: set[str] = set()
    for item in extract_paths_from_text(user_message or ""):
        if not is_path_in_workspace(item):
            continue
        path = Path(item)
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        if _looks_like_file_path(path):
            candidates.append(path)
        if len(candidates) >= _MAX_FILES:
            break
    return candidates


def looks_like_direct_file_read_request(user_message: str) -> bool:
    """用户明确要求读取白名单内文件（非改代码）。"""
    raw = (user_message or "").strip()
    if not raw or not _READ_INTENT_RE.search(raw):
        return False
    if _EDIT_INTENT_RE.search(raw):
        return False
    return bool(_workspace_file_candidates(raw))


def _read_file_block(path: Path) -> tuple[str, str | None]:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser()
    if not resolved.is_file():
        return str(resolved), None
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return str(resolved), f"读取失败: {exc}"
    if len(text) > _MAX_PREVIEW_CHARS:
        text = text[:_MAX_PREVIEW_CHARS] + "\n…(内容较长，已截断前段)"
    return str(resolved), text


def try_direct_workspace_read_reply(user_message: str) -> str | None:
    """直接读取白名单内文件并生成面向用户的回复（不经 LLM）。"""
    if not looks_like_direct_file_read_request(user_message):
        return None

    blocks: list[str] = []
    for path in _workspace_file_candidates(user_message):
        resolved, text = _read_file_block(path)
        if text is None:
            blocks.append(f"路径 `{resolved}` 找不到文件，请确认是否已保存。")
            continue
        name = Path(resolved).name
        blocks.append(f"### {name}\n`{resolved}`\n\n```\n{text}\n```")

    if not blocks:
        return None
    intro = "读到了，是这个文件：\n\n" if len(blocks) == 1 else "读到了，是这些文件：\n\n"
    return intro + "\n\n".join(blocks)


def try_direct_workspace_file_read(user_message: str) -> str | None:
    """用户消息含「代码访问目录」内文件路径时，直接读取并返回注入 Agent 的说明。"""
    raw = (user_message or "").strip()
    if not raw:
        return None

    blocks: list[str] = []
    for path in _workspace_file_candidates(raw):
        resolved, text = _read_file_block(path)
        if text is None:
            blocks.append(f"路径: {resolved}\n（文件不存在或尚不可读，请让用户确认路径）")
            continue
        blocks.append(f"路径: {Path(resolved).as_posix()}\n```\n{text}\n```")

    if not blocks:
        return None

    return (
        "【代码文件·已预读】下列路径已在「代码访问目录」白名单内（含作业等额外目录），"
        "并非「只能在 pnn_garden 内访问」。禁止再说无法访问、禁止让用户把文件复制进 pnn_garden。\n"
        + "\n\n".join(blocks)
        + "\n若需修改，用 filesystem__edit_file / write_file。"
    )
