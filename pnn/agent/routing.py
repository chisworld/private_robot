"""判断闲聊 vs 需要 MCP 工具的任务。"""

from __future__ import annotations

import re

from pnn.agent.code_edit import looks_like_code_edit_task, looks_like_project_search_task
from pnn.agent.screenshot_download import is_screenshot_download_task

# 明确需要打开浏览器 / 查网页 / 下载网络资源
_WEB_BROWSE_RE = re.compile(
    r"(?:"
    r"https?://|www\."
    r"|(?:打开|访问|浏览|跳转|前往|去|搜(?:索|一下)|查(?:一下|询)?)"
    r"(?:.{0,12})?(?:网站|网页|页面|链接|url|URL)"
    r"|(?:在|去).{0,10}(?:百度|谷歌|google|bing|wiki|知乎|bilibili|pixiv|萌娘|moegirl)"
    r"|(?:让你|帮我|请|给我).{0,20}搜"
    r"|搜(?:索|一下).{0,48}(?:信息|资料|是谁|是什么|怎么样)"
    r"|(?:下载|保存|抓取).{0,10}(?:图片|图像|图|photo|image)"
    r"|browser_|playwright"
    r")",
    re.IGNORECASE,
)

# 纯闲聊常见短句 — 即使 MCP 开着也走普通对话
_CASUAL_ONLY_RE = re.compile(
    r"^(?:"
    r"你好|您好|嗨|hi|hello|在吗|在不在|早上好|中午好|晚上好|晚安|"
    r"谢谢|感谢|辛苦了|好的|嗯|哦|啊|哈哈|嘿嘿|"
    r"怎么样|如何|为啥|为什么|什么是|是谁|"
    r"陪我|聊聊|聊天|说说|讲个|笑话|故事"
    r")[\s?？!！。~～]*$",
    re.IGNORECASE,
)


def looks_like_web_browse_task(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _CASUAL_ONLY_RE.match(raw):
        return False
    return bool(_WEB_BROWSE_RE.search(raw))


def needs_mcp_agent(
    user_message: str,
    *,
    image_base64: str | None = None,
    image_analysis: str | None = None,
) -> bool:
    """True = 需要 Agent + MCP；False = 普通 LLM 闲聊即可。"""
    text = (user_message or "").strip()
    try:
        from pnn.core.weather_query import user_asks_weather

        if user_asks_weather(text):
            return False
    except Exception:
        pass
    if (image_base64 or "").strip() or (image_analysis or "").strip():
        return True
    if is_screenshot_download_task(text):
        return True
    if looks_like_code_edit_task(text):
        return True
    if looks_like_project_search_task(text):
        return True
    if looks_like_web_browse_task(text):
        return True
    return False


def build_web_search_agent_mandate(user_message: str) -> str:
    """用户明确要求网页搜索时，覆盖角色扮演式拒绝，强制先调 Playwright。"""
    if not looks_like_web_browse_task(user_message):
        return ""
    return (
        "【本轮强制任务·优先于角色扮演】\n"
        "用户明确要求用浏览器/搜索引擎查网页（如百度）。\n"
        "你必须先调用 Playwright 工具完成搜索（例如 browser_navigate 打开 "
        "https://www.baidu.com/s?wd=关键词 或等价步骤），再根据页面内容回复。\n"
        "禁止以剧情理由（如不想被叫某名字、拒绝搜索）跳过工具；"
        "搜索结束后可用角色语气总结结果。"
    )
