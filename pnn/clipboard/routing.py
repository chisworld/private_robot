"""判断用户是否在要求处理剪贴板。"""

from __future__ import annotations

import re

_CLIPBOARD_RE = re.compile(
    r"(?:"
    r"剪贴板|粘贴板|复制(?:的|过)?(?:内容|文字|文本|那段|这段)?|"
    r"刚才复制|刚复制|我复制|clipboard"
    r")",
    re.IGNORECASE,
)

_SUMMARIZE_RE = re.compile(
    r"(?:总结|摘要|概括|归纳|整理|翻译|看看|读一下|念一下)",
    re.IGNORECASE,
)


def needs_clipboard_task(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if not _CLIPBOARD_RE.search(raw):
        return False
    if _SUMMARIZE_RE.search(raw):
        return True
    if re.search(r"(?:帮我|请|把).{0,12}(?:剪贴板|复制)", raw, re.IGNORECASE):
        return True
    return bool(re.search(r"剪贴板.{0,8}(?:里|中|的内容)", raw, re.IGNORECASE))
