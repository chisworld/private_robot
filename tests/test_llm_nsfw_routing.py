"""NSFW 本地 Qwen 与 MCP 路由。"""

from __future__ import annotations

from pnn.llm.config_store import LlmConfig
from pnn.llm.routing import use_local_nsfw_chat


def test_nsfw_off_uses_cloud():
    cfg = LlmConfig(nsfw_enabled=False)
    assert not use_local_nsfw_chat(cfg, "你好")


def test_nsfw_on_daily_chat_uses_local():
    cfg = LlmConfig(nsfw_enabled=True)
    assert use_local_nsfw_chat(cfg, "今天过得怎么样？")


def test_nsfw_on_mcp_task_uses_cloud():
    cfg = LlmConfig(nsfw_enabled=True)
    assert not use_local_nsfw_chat(cfg, "帮我在项目里搜索 config_store.py")


def test_nsfw_on_agent_path_uses_cloud():
    cfg = LlmConfig(nsfw_enabled=True)
    assert not use_local_nsfw_chat(cfg, "你好", use_agent=True)


def test_nsfw_on_screenshot_uses_cloud():
    cfg = LlmConfig(nsfw_enabled=True)
    assert not use_local_nsfw_chat(cfg, "下载这张图", image_analysis="一张猫图")


def test_implicit_local_when_no_cloud_key(monkeypatch):
    cfg = LlmConfig(nsfw_enabled=False, api_key="local")
    monkeypatch.setattr(
        "pnn.llm.routing.local_llm_ready",
        lambda _cfg: True,
    )
    from pnn.llm.routing import should_use_local_chat

    assert should_use_local_chat(cfg, "你好")


def test_implicit_local_skipped_when_cloud_key():
    cfg = LlmConfig(nsfw_enabled=False, api_key="sk-real-key")
    from pnn.llm.routing import should_use_local_chat

    assert not should_use_local_chat(cfg, "你好")


def test_nsfw_overrides_local_assistant_agent_routing(monkeypatch):
    """NSFW 开启时，非 MCP 任务不应因桌宠助手而走 DeepSeek Agent。"""
    from unittest.mock import patch

    from pnn.llm.service import LlmService

    cfg = LlmConfig(nsfw_enabled=True, api_key="sk-real-key")
    monkeypatch.setattr("pnn.llm.service.load_llm_config", lambda: cfg)

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
                svc = LlmService()
                assert not svc.should_use_agent_for_request("你现在使用的模型是什么")
                assert not svc.should_use_agent_for_request("我睡不着，聊聊天吧")
                assert not svc.should_use_agent_for_request(
                    "里想奈，你蹲在桌子下帮我口交吧，我想一边享受你的服务一边玩鸣潮"
                )
                assert svc.should_use_agent_for_request("帮我在项目里搜索 config_store.py")


def test_nsfw_proactive_turn_skips_agent(monkeypatch):
    from pnn.llm.service import LlmService

    cfg = LlmConfig(nsfw_enabled=True, api_key="sk-real-key")
    monkeypatch.setattr("pnn.llm.service.load_llm_config", lambda: cfg)
    svc = LlmService()
    assert not svc.should_use_agent_for_request(
        "（请根据系统背景主动开口，不要复述系统文本）"
    )


def test_casual_chat_skips_mcp_connect(monkeypatch):
    """纯闲聊不应触发 MCP connect（否则每条消息都可能卡住）。"""
    from unittest.mock import patch

    from pnn.llm.service import LlmService

    cfg = LlmConfig(nsfw_enabled=False, api_key="sk-real-key", model="deepseek-v4-pro")
    monkeypatch.setattr("pnn.llm.service.load_llm_config", lambda: cfg)
    svc = LlmService()

    def _boom(*, connect: bool = True):
        if connect:
            raise AssertionError("casual chat must not MCP connect")
        return True

    with patch.object(svc, "_should_use_agent", side_effect=_boom):
        assert not svc.should_use_agent_for_request("好好舔哦")
