"""Tests for AI intent routing for local assistant."""

from __future__ import annotations

from unittest.mock import patch

from pnn.agent.local_assistant import should_route_local_assistant_to_agent


def test_local_assistant_routes_implicit_system_control():
    with patch(
        "pnn.system_control.service.system_control_service.chat_enabled",
        return_value=True,
    ):
        with patch(
            "pnn.launch_apps.service.launch_apps_service.chat_enabled",
            return_value=False,
        ):
            with patch(
                "pnn.clipboard.service.clipboard_service.chat_enabled",
                return_value=False,
            ):
                assert should_route_local_assistant_to_agent("屏幕有点刺眼")
                assert should_route_local_assistant_to_agent("能不能暗一点")
                assert should_route_local_assistant_to_agent("帮我打开记事本")
                assert not should_route_local_assistant_to_agent("你好")
                assert not should_route_local_assistant_to_agent("")
                assert not should_route_local_assistant_to_agent(
                    "里想奈，你蹲在桌子下帮我口交吧，我想一边享受你的服务一边玩鸣潮"
                )
