"""剪贴板文本读取（Qt）。"""

from __future__ import annotations

import logging
import threading
from typing import Any

from pnn.clipboard.config_store import (
    CLIPBOARD_CONFIG_PATH,
    LOCAL_SERVER_ID,
    READ_CLIPBOARD_TOOL,
    ClipboardConfig,
    load_clipboard_config,
    save_clipboard_config,
)
from pnn.mcp.service import llm_tool_name

logger = logging.getLogger(__name__)


def read_clipboard_text(*, max_chars: int = 12000) -> str:
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        raise RuntimeError("Qt 未初始化，无法读取剪贴板")
    cb = app.clipboard()
    if cb is None:
        raise RuntimeError("剪贴板不可用")
    text = (cb.text() or "").strip()
    if not text:
        return ""
    limit = max(500, int(max_chars))
    if len(text) > limit:
        return text[: limit - 20] + "\n…(剪贴板内容已截断)"
    return text


class ClipboardService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config = load_clipboard_config()

    def reload_config(self) -> ClipboardConfig:
        with self._lock:
            self._config = load_clipboard_config()
            return self._config

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            cfg = self._config
            return {
                "enabled": cfg.enabled,
                "use_in_chat": cfg.use_in_chat,
                "max_chars": cfg.max_chars,
                "config_path": str(CLIPBOARD_CONFIG_PATH),
            }

    def update_config(self, **kwargs: Any) -> ClipboardConfig:
        with self._lock:
            cfg = load_clipboard_config()
            for key, val in kwargs.items():
                if hasattr(cfg, key) and val is not None:
                    setattr(cfg, key, val)
            save_clipboard_config(cfg)
            self._config = cfg
            return cfg

    def chat_enabled(self) -> bool:
        with self._lock:
            cfg = self._config
            return bool(cfg.enabled and cfg.use_in_chat)

    def list_tool_specs(self) -> list[dict[str, Any]]:
        if not self.chat_enabled():
            return []
        llm_name = llm_tool_name(LOCAL_SERVER_ID, READ_CLIPBOARD_TOOL)
        return [
            {
                "server_id": LOCAL_SERVER_ID,
                "server_name": "剪贴板",
                "name": READ_CLIPBOARD_TOOL,
                "llm_name": llm_name,
                "registered_name": llm_name,
                "description": (
                    "读取用户当前剪贴板中的纯文本（不含图片）。"
                    "用户要求总结/翻译/处理「剪贴板」「复制的内容」时使用；"
                    "读取后用角色语气给出摘要或按要求处理，勿逐字复读全文。"
                ),
                "input_schema": {"type": "object", "properties": {}},
            }
        ]

    def call_read_clipboard(self, _arguments: dict[str, Any] | None = None) -> str:
        if not self.chat_enabled():
            return "剪贴板读取已在设置中禁用"
        try:
            text = read_clipboard_text(max_chars=self._config.max_chars)
        except Exception as exc:
            return f"读取剪贴板失败: {exc}"
        if not text:
            return "剪贴板中没有文本（可能是空的或只有图片/文件）"
        preview = text.replace("\n", " ")[:80]
        logger.info("已读取剪贴板文本（%s 字）: %s", len(text), preview)
        return f"【剪贴板内容开始】\n{text}\n【剪贴板内容结束】"


clipboard_service = ClipboardService()
