"""filesystem 多工作区根目录。"""

from __future__ import annotations

from pnn.mcp.code_workspace import (
    FILESYSTEM_MCP_PKG,
    merged_filesystem_roots,
)
from pnn.mcp.config_store import McpConfig, McpServerConfig


def test_merged_filesystem_roots_keeps_extra_paths():
    homework = r"D:\Project\作业"
    cfg = McpConfig(filesystem_extra_roots=[homework])
    server = McpServerConfig(
        id="filesystem",
        name="项目代码",
        command="npx",
        args=["-y", FILESYSTEM_MCP_PKG, r"D:\Project\pnn_garden"],
    )
    roots = merged_filesystem_roots(cfg, existing_server=server)
    assert any("pnn_garden" in r for r in roots)
    assert any("作业" in r for r in roots)


def test_build_code_edit_instructions_lists_homework():
    from pnn.agent.code_edit import build_agent_code_edit_instructions

    text = build_agent_code_edit_instructions(include_map=False)
    assert "作业" in text or "filesystem" in text


def test_extract_paths_strips_chinese_suffix():
    from pnn.mcp.code_workspace import extract_paths_from_text

    p = r"D:\Project\作业\菌子接接乐\菌子接接乐.py"
    got = extract_paths_from_text(f"{p}，写在这里了")
    assert got == [p]


def test_path_in_workspace():
    from pnn.mcp.code_workspace import build_path_tool_mandate, is_path_in_workspace

    p = r"D:\Project\作业\菌子接接乐\菌子接接乐.py"
    assert is_path_in_workspace(p) or is_path_in_workspace(r"D:\Project\pnn_garden\README.md")
    mandate = build_path_tool_mandate(f"读一下 {p}")
    if is_path_in_workspace(p):
        assert "filesystem" in mandate
