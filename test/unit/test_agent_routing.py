from pnn.agent.routing import needs_mcp_agent, looks_like_web_browse_task


def test_casual_chat_skips_agent():
    assert not needs_mcp_agent("你好呀主人")
    assert not needs_mcp_agent("今天过得怎么样？")
    assert not needs_mcp_agent("陪我聊聊天")
    assert not needs_mcp_agent("你喜欢什么颜色")


def test_web_task_uses_agent():
    assert looks_like_web_browse_task("帮我去萌娘百科打开这个页面")
    assert needs_mcp_agent("请访问 https://example.com 下载图片")


def test_screenshot_uses_agent():
    assert needs_mcp_agent("", image_analysis="游戏截图，角色是柚子")
    assert needs_mcp_agent("去 moegirl 找图", image_base64="abc")
