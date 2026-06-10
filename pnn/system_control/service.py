"""系统操控 Agent 工具与白名单。"""

from __future__ import annotations

import logging
import threading
from typing import Any

from pnn.mcp.service import llm_tool_name
from pnn.system_control.config_store import (
    CANCEL_SHUTDOWN_TOOL,
    EMPTY_RECYCLE_BIN_TOOL,
    LOCAL_SERVER_ID,
    SCHEDULE_SHUTDOWN_TOOL,
    SET_BRIGHTNESS_TOOL,
    SET_VOLUME_TOOL,
    SystemControlConfig,
    load_system_control_config,
    save_system_control_config,
)

logger = logging.getLogger(__name__)


class SystemControlService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config = load_system_control_config()

    def reload_config(self) -> SystemControlConfig:
        with self._lock:
            self._config = load_system_control_config()
            return self._config

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            cfg = self._config
            return {
                "enabled": cfg.enabled,
                "use_in_chat": cfg.use_in_chat,
                "allow_shutdown": cfg.allow_shutdown,
                "allow_recycle_bin": cfg.allow_recycle_bin,
                "allow_volume": cfg.allow_volume,
                "allow_brightness": cfg.allow_brightness,
                "shutdown_confirm_minutes": cfg.shutdown_confirm_minutes,
            }

    def update_config(self, **kwargs: Any) -> SystemControlConfig:
        with self._lock:
            cfg = load_system_control_config()
            for key, val in kwargs.items():
                if hasattr(cfg, key) and val is not None:
                    setattr(cfg, key, val)
            save_system_control_config(cfg)
            self._config = cfg
            return cfg

    def chat_enabled(self) -> bool:
        with self._lock:
            cfg = self._config
            return bool(cfg.enabled and cfg.use_in_chat)

    def list_tool_specs(self) -> list[dict[str, Any]]:
        if not self.chat_enabled():
            return []
        cfg = self._config
        specs: list[dict[str, Any]] = []
        if cfg.allow_volume:
            specs.append(
                self._spec(
                    SET_VOLUME_TOOL,
                    "调节系统主音量：percent=绝对值 0–100；delta=相对增减"
                    "（用户说「调小10」→ delta=-10，「调大5」→ delta=5）。",
                    {
                        "percent": {"type": "integer", "description": "绝对音量 0–100"},
                        "delta": {
                            "type": "integer",
                            "description": "相对增减，正数变大、负数变小，如 -10 或 5",
                        },
                    },
                )
            )
        if cfg.allow_brightness:
            specs.append(
                self._spec(
                    SET_BRIGHTNESS_TOOL,
                    "调节屏幕亮度：percent=绝对值 0–100；delta=相对增减"
                    "（用户说「调高8」→ delta=8，「调暗一点」→ delta=-10）。",
                    {
                        "percent": {"type": "integer", "description": "绝对亮度 0–100"},
                        "delta": {
                            "type": "integer",
                            "description": "相对增减，正数变亮、负数变暗，如 8 或 -10",
                        },
                    },
                )
            )
        if cfg.allow_recycle_bin:
            specs.append(
                self._spec(
                    EMPTY_RECYCLE_BIN_TOOL,
                    "清空 Windows 回收站。用户说「清空回收站」时使用。",
                    {},
                )
            )
        if cfg.allow_shutdown:
            specs.append(
                self._spec(
                    SCHEDULE_SHUTDOWN_TOOL,
                    "计划在若干分钟后关机。用户说「30分钟后关机」时使用。",
                    {
                        "minutes": {
                            "type": "integer",
                            "description": "多少分钟后关机，至少 1",
                        }
                    },
                    required=["minutes"],
                )
            )
            specs.append(
                self._spec(
                    CANCEL_SHUTDOWN_TOOL,
                    "取消已计划的关机。",
                    {},
                )
            )
        return specs

    def _spec(
        self,
        tool_name: str,
        description: str,
        properties: dict[str, Any],
        *,
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        llm_name = llm_tool_name(LOCAL_SERVER_ID, tool_name)
        return {
            "server_id": LOCAL_SERVER_ID,
            "server_name": "本机系统操控",
            "name": tool_name,
            "llm_name": llm_name,
            "registered_name": llm_name,
            "description": description,
            "input_schema": schema,
        }

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None) -> str:
        args = arguments or {}
        cfg = self._config
        from pnn.system_control import windows_ops as ops

        if tool_name == SET_VOLUME_TOOL:
            if not cfg.allow_volume:
                return "音量调节已在设置中禁用"
            try:
                if args.get("delta") is not None:
                    return ops.adjust_master_volume(int(args["delta"]))
                percent = args.get("percent", args.get("level"))
                if percent is None:
                    return "缺少参数：相对调节用 delta（如调小10 → delta=-10），绝对值用 percent"
                return ops.set_master_volume_percent(int(percent))
            except Exception as exc:
                return f"设置音量失败: {exc}"

        if tool_name == SET_BRIGHTNESS_TOOL:
            if not cfg.allow_brightness:
                return "亮度调节已在设置中禁用"
            try:
                if args.get("percent") is not None:
                    return ops.set_brightness_percent(int(args["percent"]))
                if args.get("delta") is not None:
                    return ops.adjust_brightness(int(args["delta"]))
                return "缺少参数：相对调节用 delta（如调高8 → delta=8），绝对值用 percent"
            except Exception as exc:
                return f"调节亮度失败: {exc}"

        if tool_name == EMPTY_RECYCLE_BIN_TOOL:
            if not cfg.allow_recycle_bin:
                return "清空回收站已在设置中禁用"
            try:
                return ops.empty_recycle_bin()
            except Exception as exc:
                return f"清空回收站失败: {exc}"

        if tool_name == SCHEDULE_SHUTDOWN_TOOL:
            if not cfg.allow_shutdown:
                return "定时关机已在设置中禁用"
            minutes = int(args.get("minutes") or 0)
            if minutes < 1:
                return "minutes 至少为 1"
            if minutes < cfg.shutdown_confirm_minutes:
                return (
                    f"安全限制：定时关机至少 {cfg.shutdown_confirm_minutes} 分钟后，"
                    f"请让用户确认或改更大数值"
                )
            try:
                return ops.schedule_shutdown(minutes)
            except Exception as exc:
                return f"计划关机失败: {exc}"

        if tool_name == CANCEL_SHUTDOWN_TOOL:
            if not cfg.allow_shutdown:
                return "关机相关操作已在设置中禁用"
            try:
                return ops.cancel_shutdown()
            except Exception as exc:
                return f"取消关机失败: {exc}"

        return f"未知系统工具: {tool_name}"


system_control_service = SystemControlService()
