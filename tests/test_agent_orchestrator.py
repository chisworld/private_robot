"""AgentOrchestrator 集成测试（mock LLM / MCP，覆盖主循环分支）。"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pnn.agent.orchestrator import AgentOrchestrator
from pnn.mcp.config_store import McpConfig


def _tool(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "parameters": {}}}


def _all_tools() -> list[dict[str, Any]]:
    return [
        _tool("playwright__browser_navigate"),
        _tool("filesystem__read_text_file"),
        _tool("local__launch_app"),
        _tool("local__set_volume"),
    ]


def _run_orchestrator(
    user_message: str,
    *,
    chat_responses: list[dict[str, Any]],
    tool_result: str = "ok",
    max_steps: int = 12,
    launch_enabled: bool = False,
    system_enabled: bool = False,
    clipboard_enabled: bool = False,
) -> tuple[list[tuple[str, str]], list[list[dict[str, Any]]], list[list[dict[str, Any]]]]:
    client = MagicMock()
    client.model = "deepseek-test"
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    captured_work: list[list[dict[str, Any]]] = []
    captured_tools: list[list[dict[str, Any]]] = []
    responses = list(chat_responses)
    call_idx = {"n": 0}

    def _capture_chat(work: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        captured_work.append(list(work))
        captured_tools.append(list(kwargs.get("tools") or []))
        idx = call_idx["n"]
        call_idx["n"] += 1
        return responses[idx]

    client.chat_completion.side_effect = _capture_chat

    cfg = McpConfig(max_agent_steps=max_steps)
    orch = AgentOrchestrator()

    with patch("pnn.agent.orchestrator.load_mcp_config", return_value=cfg):
        with patch("pnn.agent.orchestrator.mcp_service.tools_for_openai", return_value=_all_tools()):
            with patch(
                "pnn.agent.orchestrator.mcp_service.call_tool_by_llm_name",
                return_value={"result": tool_result},
            ):
                with patch(
                    "pnn.launch_apps.service.launch_apps_service.chat_enabled",
                    return_value=launch_enabled,
                ):
                    with patch(
                        "pnn.system_control.service.system_control_service.chat_enabled",
                        return_value=system_enabled,
                    ):
                        with patch(
                            "pnn.clipboard.service.clipboard_service.chat_enabled",
                            return_value=clipboard_enabled,
                        ):
                            with patch(
                                "pnn.agent.orchestrator.try_direct_launch_app",
                                return_value=None,
                            ):
                                events = list(
                                    orch.iter_turn(
                                        messages,
                                        client,
                                        temperature=0.7,
                                        max_tokens=256,
                                    )
                                )
    return events, captured_work, captured_tools


def test_orchestrator_streams_final_text() -> None:
    events, _, _ = _run_orchestrator(
        "你好",
        chat_responses=[
            {"model": "deepseek-test", "message": {"content": "你好呀", "tool_calls": []}},
        ],
    )
    deltas = [chunk for kind, chunk in events if kind == "delta"]
    assert "".join(deltas) == "你好呀"
    assert any(kind == "status" for kind, _ in events)


def test_orchestrator_tool_call_then_reply() -> None:
    events, work_history, _ = _run_orchestrator(
        "读一下 README",
        chat_responses=[
            {
                "model": "deepseek-test",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "function": {
                                "name": "filesystem__read_text_file",
                                "arguments": '{"path":"README.md"}',
                            },
                        }
                    ],
                },
            },
            {"model": "deepseek-test", "message": {"content": "读完了", "tool_calls": []}},
        ],
        tool_result="# Project",
    )
    assert "".join(chunk for kind, chunk in events if kind == "delta") == "读完了"
    assert any("filesystem__read_text_file" in str(msg) for msg in work_history[-1])
    assert any(kind == "status" and "filesystem__read_text_file" in chunk for kind, chunk in events)


def test_orchestrator_local_only_filters_tools() -> None:
    _, _, captured_tools = _run_orchestrator(
        "你好",
        chat_responses=[
            {"model": "deepseek-test", "message": {"content": "嗯", "tool_calls": []}},
        ],
        launch_enabled=True,
    )
    names = [
        str((t.get("function") or {}).get("name") or "")
        for t in captured_tools[0]
    ]
    assert names
    assert all(name.startswith("local__") for name in names)


def test_orchestrator_code_task_hides_playwright_tools() -> None:
    _, _, captured_tools = _run_orchestrator(
        "帮我在项目里改一下 controller.py 的注释",
        chat_responses=[
            {"model": "deepseek-test", "message": {"content": "改好了", "tool_calls": []}},
        ],
    )
    names = [
        str((t.get("function") or {}).get("name") or "")
        for t in captured_tools[0]
    ]
    assert names
    assert not any(name.startswith("playwright__") for name in names)
    assert any(name.startswith("filesystem__") for name in names)


def test_orchestrator_injects_direct_launch_context() -> None:
    client = MagicMock()
    client.model = "deepseek-test"
    captured_work: list[list[dict[str, Any]]] = []

    def _chat(work: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        captured_work.append(list(work))
        return {"model": "deepseek-test", "message": {"content": "开好啦", "tool_calls": []}}

    client.chat_completion.side_effect = _chat
    orch = AgentOrchestrator()

    with patch("pnn.agent.orchestrator.load_mcp_config", return_value=McpConfig()):
        with patch(
            "pnn.agent.orchestrator.mcp_service.tools_for_openai",
            return_value=_all_tools(),
        ):
            with patch(
                "pnn.launch_apps.service.launch_apps_service.chat_enabled",
                return_value=True,
            ):
                with patch(
                    "pnn.system_control.service.system_control_service.chat_enabled",
                    return_value=False,
                ):
                    with patch(
                        "pnn.clipboard.service.clipboard_service.chat_enabled",
                        return_value=False,
                    ):
                        with patch(
                            "pnn.agent.orchestrator.try_direct_launch_app",
                            return_value="已启动 记事本",
                        ):
                            list(
                                orch.iter_turn(
                                    [{"role": "user", "content": "打开记事本"}],
                                    client,
                                    temperature=0.7,
                                    max_tokens=128,
                                )
                            )

    system_text = "\n".join(
        str(msg.get("content") or "")
        for msg in captured_work[0]
        if msg.get("role") == "system"
    )
    assert "快捷启动" in system_text
    assert "已启动 记事本" in system_text


def test_orchestrator_injects_direct_system_control_context() -> None:
    client = MagicMock()
    client.model = "deepseek-test"
    captured_work: list[list[dict[str, Any]]] = []

    def _chat(work: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        captured_work.append(list(work))
        return {"model": "deepseek-test", "message": {"content": "调好啦", "tool_calls": []}}

    client.chat_completion.side_effect = _chat
    orch = AgentOrchestrator()

    with patch("pnn.agent.orchestrator.load_mcp_config", return_value=McpConfig()):
        with patch(
            "pnn.agent.orchestrator.mcp_service.tools_for_openai",
            return_value=_all_tools(),
        ):
            with patch(
                "pnn.launch_apps.service.launch_apps_service.chat_enabled",
                return_value=False,
            ):
                with patch(
                    "pnn.system_control.service.system_control_service.chat_enabled",
                    return_value=True,
                ):
                    with patch(
                        "pnn.clipboard.service.clipboard_service.chat_enabled",
                        return_value=False,
                    ):
                        with patch(
                            "pnn.agent.orchestrator.try_direct_system_control",
                            return_value="音量已调到 30%",
                        ):
                            list(
                                orch.iter_turn(
                                    [{"role": "user", "content": "声音太大了"}],
                                    client,
                                    temperature=0.7,
                                    max_tokens=128,
                                )
                            )

    system_text = "\n".join(
        str(msg.get("content") or "")
        for msg in captured_work[0]
        if msg.get("role") == "system"
    )
    assert "系统操控" in system_text
    assert "音量已调到 30%" in system_text


def test_orchestrator_raises_when_exceeding_max_steps() -> None:
    orch = AgentOrchestrator()
    client = MagicMock()
    client.model = "deepseek-test"
    client.chat_completion.return_value = {
        "model": "deepseek-test",
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "id": "loop",
                    "function": {"name": "filesystem__read_text_file", "arguments": "{}"},
                }
            ],
        },
    }

    with patch("pnn.agent.orchestrator.load_mcp_config", return_value=McpConfig(max_agent_steps=1)):
        with patch("pnn.agent.orchestrator.mcp_service.tools_for_openai", return_value=_all_tools()):
            with patch(
                "pnn.agent.orchestrator.mcp_service.call_tool_by_llm_name",
                return_value={"result": "x"},
            ):
                with patch(
                    "pnn.launch_apps.service.launch_apps_service.chat_enabled",
                    return_value=False,
                ):
                    with patch(
                        "pnn.system_control.service.system_control_service.chat_enabled",
                        return_value=False,
                    ):
                        with patch(
                            "pnn.clipboard.service.clipboard_service.chat_enabled",
                            return_value=False,
                        ):
                            with pytest.raises(RuntimeError, match="超过最大步数"):
                                list(
                                    orch.iter_turn(
                                        [{"role": "user", "content": "读文件"}],
                                        client,
                                        temperature=0.7,
                                        max_tokens=128,
                                    )
                                )
