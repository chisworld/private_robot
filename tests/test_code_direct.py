"""代码路径直达预读。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from pnn.agent.code_direct import (
    looks_like_direct_file_read_request,
    try_direct_workspace_file_read,
    try_direct_workspace_read_reply,
)


def test_direct_read_in_workspace(tmp_path: Path, monkeypatch):
    homework = tmp_path / "homework"
    homework.mkdir()
    target = homework / "demo.py"
    target.write_text("print('hi')\n", encoding="utf-8")

    def fake_is_path_in_workspace(path: str) -> bool:
        return str(homework) in path

    monkeypatch.setattr(
        "pnn.mcp.code_workspace.is_path_in_workspace",
        fake_is_path_in_workspace,
    )
    msg = f"读一下 {target}"
    out = try_direct_workspace_file_read(msg)
    assert out is not None
    assert "已预读" in out
    assert "print('hi')" in out


def test_direct_read_reply_bypasses_llm(tmp_path: Path, monkeypatch):
    homework = tmp_path / "homework"
    homework.mkdir()
    target = homework / "demo.py"
    target.write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "pnn.mcp.code_workspace.is_path_in_workspace",
        lambda p: str(homework) in p,
    )
    msg = f"读一下 {target}"
    assert looks_like_direct_file_read_request(msg)
    reply = try_direct_workspace_read_reply(msg)
    assert reply is not None
    assert "读到了" in reply
    assert "x = 1" in reply
    assert "demo.py" in reply


def test_direct_read_skips_edit_intent(tmp_path: Path, monkeypatch):
    target = tmp_path / "demo.py"
    target.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr("pnn.mcp.code_workspace.is_path_in_workspace", lambda _p: True)
    msg = f"改一下 {target} 里的变量"
    assert not looks_like_direct_file_read_request(msg)
    assert try_direct_workspace_read_reply(msg) is None


def test_direct_read_skips_outside_workspace(tmp_path: Path, monkeypatch):
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "pnn.mcp.code_workspace.is_path_in_workspace",
        lambda _p: False,
    )
    assert try_direct_workspace_file_read(f"读一下 {outside}") is None
