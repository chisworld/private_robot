"""filesystem MCP：桌宠内读写代码的工作区配置（支持多根目录）。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pnn.core.paths import PROJECT_ROOT
from pnn.mcp.config_store import McpConfig, McpServerConfig, get_server

logger = logging.getLogger(__name__)

FILESYSTEM_SERVER_ID = "filesystem"
FILESYSTEM_MCP_PKG = "@modelcontextprotocol/server-filesystem"

# 默认额外工作区（可在 data/config/mcp.json 的 filesystem_extra_roots 覆盖/追加）
_DEFAULT_EXTRA_ROOTS: tuple[str, ...] = (r"D:\Project\作业",)

_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"'<>|?*]+")
_POSIX_PATH_RE = re.compile(r"(?<![A-Za-z:])/(?:[^\s\"'<>|?*]+/)*[^\s\"'<>|?*]+")


def code_workspace_root() -> str:
    return str(PROJECT_ROOT.resolve())


def _normalize_root(path: str) -> str:
    p = Path(path).expanduser()
    try:
        return str(p.resolve())
    except OSError:
        return str(p)


def _roots_from_server_args(args: list[str]) -> list[str]:
    if FILESYSTEM_MCP_PKG not in args:
        return []
    idx = args.index(FILESYSTEM_MCP_PKG)
    roots: list[str] = []
    for arg in args[idx + 1 :]:
        if arg.startswith("-"):
            break
        text = (arg or "").strip()
        if text:
            roots.append(_normalize_root(text))
    return roots


def merged_filesystem_roots(
    cfg: McpConfig,
    *,
    existing_server: McpServerConfig | None = None,
) -> list[str]:
    """合并主项目根、配置项与已有 server args 中的目录（去重保序）。"""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        text = (path or "").strip()
        if not text:
            return
        key = _normalize_root(text).casefold()
        if key in seen:
            return
        seen.add(key)
        ordered.append(_normalize_root(text))

    add(code_workspace_root())
    for item in getattr(cfg, "filesystem_extra_roots", None) or []:
        add(str(item))
    for item in _DEFAULT_EXTRA_ROOTS:
        add(item)
    if existing_server is not None:
        for item in _roots_from_server_args(list(existing_server.args)):
            add(item)
    return ordered


def list_filesystem_workspace_roots() -> list[str]:
    """当前 filesystem MCP 可访问的根目录列表（供 Agent 提示注入）。"""
    from pnn.mcp.config_store import load_mcp_config

    cfg = load_mcp_config()
    server = get_server(cfg, FILESYSTEM_SERVER_ID)
    if server is None:
        return [code_workspace_root()]
    roots = merged_filesystem_roots(cfg, existing_server=server)
    return roots or [code_workspace_root()]


def is_path_in_workspace(path: str) -> bool:
    """判断路径是否落在任一工作区根目录下。"""
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        return False
    try:
        target = Path(raw).expanduser().resolve()
    except OSError:
        target = Path(raw).expanduser()
    for root in list_filesystem_workspace_roots():
        try:
            base = Path(root).expanduser().resolve()
        except OSError:
            base = Path(root).expanduser()
        try:
            target.relative_to(base)
            return True
        except ValueError:
            continue
    return False


def _clean_extracted_path(path: str) -> str:
    """去掉路径尾部误捕获的中文标点或说明文字（保留盘符 D:）。"""
    p = (path or "").strip().strip('"').strip("'")
    for sep in ("，", ",", "。", "；", "：", "！", "!", "？", "?", "）", ")", "（", "("):
        if sep in p:
            p = p.split(sep, 1)[0]
    return p.rstrip(".,，。；;：:!！?？")


def extract_paths_from_text(text: str) -> list[str]:
    """从用户消息中提取可能的文件/目录路径。"""
    raw = text or ""
    found: list[str] = []
    seen: set[str] = set()
    for pat in (_WIN_PATH_RE, _POSIX_PATH_RE):
        for m in pat.finditer(raw):
            p = _clean_extracted_path(m.group(0))
            if p and p not in seen:
                seen.add(p)
                found.append(p)
    return found


def build_path_tool_mandate(user_text: str) -> str:
    """用户消息里含允许路径时，强制 Agent 走 filesystem 工具。"""
    paths = [p for p in extract_paths_from_text(user_text) if is_path_in_workspace(p)]
    if not paths:
        return ""
    shown = "\n".join(f"  - {Path(p).as_posix()}" for p in paths[:5])
    roots = list_filesystem_workspace_roots()
    root_hint = "、".join(Path(r).name for r in roots[:4]) or "已配置目录"
    return (
        "【强制·代码路径】用户给出的下列路径已在「代码访问目录」白名单内"
        f"（含 {root_hint} 等根目录，不限于 pnn_garden），"
        "你必须用 filesystem MCP 读写（如 read_text_file / edit_file / write_file），"
        "禁止口头说「无法访问」「在项目外」「只能复制到 pnn_garden」。\n"
        f"{shown}\n"
        "读完再回答；若要修改，先 read 再 edit。"
    )


def default_filesystem_server() -> McpServerConfig:
    roots = merged_filesystem_roots(McpConfig())
    return McpServerConfig(
        id=FILESYSTEM_SERVER_ID,
        name="项目代码",
        enabled=True,
        transport="stdio",
        command="npx",
        args=["-y", FILESYSTEM_MCP_PKG, *roots],
        tool_prefix="",
    )


def ensure_filesystem_server(cfg: McpConfig) -> bool:
    """确保 mcp.json 含 filesystem 服务，且 args 包含全部工作区根目录。返回是否改动了 args。"""
    server = get_server(cfg, FILESYSTEM_SERVER_ID)
    roots = merged_filesystem_roots(cfg, existing_server=server)
    if not roots:
        roots = [code_workspace_root()]

    if server is None:
        cfg.servers.append(
            McpServerConfig(
                id=FILESYSTEM_SERVER_ID,
                name="项目代码",
                enabled=True,
                transport="stdio",
                command="npx",
                args=["-y", FILESYSTEM_MCP_PKG, *roots],
                tool_prefix="",
            )
        )
        logger.info("已注册 filesystem MCP，工作区: %s", roots)
        return True

    prefix: list[str] = []
    args = list(server.args)
    if FILESYSTEM_MCP_PKG in args:
        idx = args.index(FILESYSTEM_MCP_PKG)
        prefix = args[: idx + 1]
    else:
        prefix = ["-y", FILESYSTEM_MCP_PKG]
    new_args = [*prefix, *roots]
    changed = list(server.args) != new_args
    server.args = new_args
    if changed:
        logger.info("filesystem MCP 工作区已更新: %s", roots)
    else:
        logger.debug("filesystem MCP 工作区: %s", roots)
    return changed
