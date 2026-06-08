"""判断用户是否在要求打开白名单程序。"""

from __future__ import annotations

import re

# 与 agent/routing 中 _CASUAL_ONLY_RE 保持一致，避免误触发
_CASUAL_ONLY_RE = re.compile(
    r"^(?:"
    r"你好|您好|嗨|hi|hello|在吗|在不在|早上好|中午好|晚上好|晚安|"
    r"谢谢|感谢|辛苦了|好的|嗯|哦|啊|哈哈|嘿嘿|"
    r"怎么样|如何|为啥|为什么|什么是|是谁|"
    r"陪我|聊聊|聊天|说说|讲个|笑话|故事"
    r")[\s?？!！。~～]*$",
    re.IGNORECASE,
)

_LAUNCH_APP_RE = re.compile(
    r"(?:"
    r"(?:请|帮我|帮忙|给我|替我)?"
    r"(?:打开|启动|运行|开一下|开下|开开|开启|launch|open|start)"
    r"(?:一下|下|个)?"
    r"|(?:能不能|可以|会不会)(?:.{0,8})?(?:打开|启动|运行)"
    r")",
    re.IGNORECASE,
)


def needs_launch_app_task(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _CASUAL_ONLY_RE.match(raw):
        return False
    return bool(_LAUNCH_APP_RE.search(raw))
