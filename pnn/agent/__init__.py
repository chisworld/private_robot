"""AI Agent 编排：桌宠对话中的 MCP 工具循环。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pnn.agent.orchestrator import AgentOrchestrator

__all__ = ["AgentOrchestrator"]


def __getattr__(name: str):
    if name == "AgentOrchestrator":
        from pnn.agent.orchestrator import AgentOrchestrator

        return AgentOrchestrator
    raise AttributeError(name)
