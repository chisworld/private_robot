"""filesystem MCP：桌宠内读写项目代码的工作区配置。"""

from __future__ import annotations

from pnn.core.paths import PROJECT_ROOT
from pnn.mcp.config_store import McpConfig, McpServerConfig, get_server

FILESYSTEM_SERVER_ID = "filesystem"
FILESYSTEM_MCP_PKG = "@modelcontextprotocol/server-filesystem"


def code_workspace_root() -> str:
    return str(PROJECT_ROOT.resolve())


def default_filesystem_server() -> McpServerConfig:
    return McpServerConfig(
        id=FILESYSTEM_SERVER_ID,
        name="项目代码",
        enabled=True,
        transport="stdio",
        command="npx",
        args=["-y", FILESYSTEM_MCP_PKG, code_workspace_root()],
        tool_prefix="",
    )


def ensure_filesystem_server(cfg: McpConfig) -> None:
    """确保 mcp.json 含 filesystem 服务，且根目录指向当前项目。"""
    root = code_workspace_root()
    server = get_server(cfg, FILESYSTEM_SERVER_ID)
    if server is None:
        cfg.servers.append(default_filesystem_server())
        return

    args = list(server.args)
    if FILESYSTEM_MCP_PKG in args:
        idx = args.index(FILESYSTEM_MCP_PKG)
        if idx + 1 < len(args):
            args[idx + 1] = root
        else:
            args.append(root)
    else:
        args = ["-y", FILESYSTEM_MCP_PKG, root]
    server.args = args
