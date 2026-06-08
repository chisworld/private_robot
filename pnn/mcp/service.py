"""MCP 服务：连接配置中的 MCP Server，列出/调用工具。"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from pnn.mcp.bridge import MCPBridge
from pnn.mcp.config_store import (
    MCP_CONFIG_PATH,
    McpConfig,
    McpServerConfig,
    PLAYWRIGHT_SERVER_ID,
    ensure_playwright_output_dir,
    get_server,
    is_playwright_headless,
    load_mcp_config,
    playwright_browser_channel,
    save_mcp_config,
    set_playwright_headless,
)
from pnn.mcp.runtime import run_on_bridge_owner
from pnn.mcp.storage import mcp_storage_root, organize_staging, purge_staging_images

logger = logging.getLogger(__name__)


def llm_tool_name(server_id: str, tool_name: str) -> str:
    return f"{server_id}__{tool_name}"


def parse_llm_tool_name(name: str) -> tuple[str, str]:
    raw = (name or "").strip()
    if "__" not in raw:
        raise ValueError(f"无法解析工具名: {raw}")
    server_id, tool = raw.split("__", 1)
    if not server_id or not tool:
        raise ValueError(f"无法解析工具名: {raw}")
    return server_id, tool


@dataclass
class McpToolInfo:
    server_id: str
    server_name: str
    name: str
    registered_name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class _LiveConnection:
    server: McpServerConfig
    bridge: MCPBridge
    tools: list[McpToolInfo] = field(default_factory=list)
    error: str = ""


def _tool_to_dict(tool_obj: Any) -> dict[str, Any]:
    md = getattr(tool_obj, "model_dump", None)
    if callable(md):
        d = md(mode="json", by_alias=True)
        if isinstance(d, dict):
            return d
    name = getattr(tool_obj, "name", None)
    if not isinstance(name, str):
        raise TypeError(f"无法序列化 MCP 工具: {tool_obj!r}")
    desc = getattr(tool_obj, "description", None) or ""
    schema = getattr(tool_obj, "inputSchema", None) or getattr(tool_obj, "input_schema", None)
    out: dict[str, Any] = {"name": name, "description": str(desc)}
    if schema is not None:
        if hasattr(schema, "model_dump"):
            out["inputSchema"] = schema.model_dump(mode="json", by_alias=True)
        elif isinstance(schema, dict):
            out["inputSchema"] = schema
    return out


class McpService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config = load_mcp_config()
        self._connections: dict[str, _LiveConnection] = {}
        self._sdk_available = self._check_sdk()
        self._agent_page_url: str = ""
        self._single_image_download = False
        self._agent_images_saved = 0

    @staticmethod
    def _check_sdk() -> bool:
        try:
            import mcp  # noqa: F401

            return True
        except ImportError:
            return False

    def reload_config(self) -> McpConfig:
        with self._lock:
            try:
                self._disconnect_all_unlocked()
            except Exception as exc:
                logger.warning("MCP reload 断开连接失败: %s", exc)
            self._config = load_mcp_config()
            return self._config

    @staticmethod
    def _disconnect_needed(before, after) -> bool:
        """仅连接相关项变化时才断开 MCP（避免保存设置卡顿）。"""
        if before.enabled != after.enabled:
            return True
        if before.use_in_chat != after.use_in_chat:
            return True
        if is_playwright_headless(before) != is_playwright_headless(after):
            return True
        if playwright_browser_channel(before) != playwright_browser_channel(after):
            return True
        before_map = {s.id: s.enabled for s in before.servers}
        after_map = {s.id: s.enabled for s in after.servers}
        return before_map != after_map

    def update_config(
        self,
        *,
        enabled: bool | None = None,
        use_in_chat: bool | None = None,
        max_agent_steps: int | None = None,
        tool_result_max_chars: int | None = None,
        default_call_timeout: float | None = None,
        preload_on_startup: bool | None = None,
        server_enabled: dict[str, bool] | None = None,
        playwright_headless: bool | None = None,
    ) -> McpConfig:
        with self._lock:
            before = load_mcp_config()
            cfg = load_mcp_config()
            if enabled is not None:
                cfg.enabled = bool(enabled)
            if use_in_chat is not None:
                cfg.use_in_chat = bool(use_in_chat)
            if max_agent_steps is not None:
                from pnn.mcp.config_store import MAX_AGENT_STEPS_LIMIT

                cfg.max_agent_steps = max(1, min(MAX_AGENT_STEPS_LIMIT, int(max_agent_steps)))
            if tool_result_max_chars is not None:
                cfg.tool_result_max_chars = max(500, min(50000, int(tool_result_max_chars)))
            if default_call_timeout is not None:
                cfg.default_call_timeout = max(5.0, min(600.0, float(default_call_timeout)))
            if preload_on_startup is not None:
                cfg.preload_on_startup = bool(preload_on_startup)
            if server_enabled:
                for s in cfg.servers:
                    if s.id in server_enabled:
                        s.enabled = bool(server_enabled[s.id])
            if playwright_headless is not None:
                set_playwright_headless(cfg, bool(playwright_headless))
            from pnn.mcp.config_store import ensure_playwright_browser

            ensure_playwright_browser(cfg)
            ensure_playwright_output_dir(cfg)
            save_mcp_config(cfg)
            if self._disconnect_needed(before, cfg):
                try:
                    self._disconnect_all_unlocked()
                except Exception as exc:
                    logger.warning("MCP 断开旧连接失败（配置已写入磁盘）: %s", exc)
            self._config = cfg
            return cfg

    def reset_agent_context(self) -> None:
        """新一轮 Agent 任务开始时清空页面上下文。"""
        self._agent_page_url = ""
        self._single_image_download = False
        self._agent_images_saved = 0

    def set_single_image_download(self, enabled: bool = True) -> None:
        """截图寻图任务：整轮对话只允许保存 1 张图片。"""
        self._single_image_download = bool(enabled)

    def single_image_download_active(self) -> bool:
        return self._single_image_download

    def _remaining_image_quota(self) -> int | None:
        if not self._single_image_download:
            return None
        return max(0, 1 - self._agent_images_saved)

    @staticmethod
    def _guard_playwright_download(
        tool_name: str,
        arguments: dict[str, Any],
        *,
        single_image: bool,
        images_saved: int,
    ) -> str | None:
        if not single_image:
            return None
        name = (tool_name or "").strip().lower()
        if images_saved >= 1 and name in ("browser_run_code", "browser_evaluate"):
            return (
                "【系统限制】本轮截图寻图任务已成功保存 1 张目标图片，禁止继续下载。"
                "请直接向用户汇报已保存路径并结束，勿再调用下载相关工具。"
            )
        if name == "browser_run_code" and images_saved < 1:
            from pnn.agent.screenshot_download import looks_like_bulk_image_download

            code = str(
                arguments.get("code")
                or arguments.get("script")
                or arguments.get("expression")
                or ""
            )
            if looks_like_bulk_image_download(code):
                return (
                    "【系统拒绝】脚本疑似批量下载页面全部图片（含循环或 querySelectorAll）。"
                    "本任务只允许下载与截图分析最匹配的 1 张原图。"
                    "请 browser_snapshot 定位单张目标，再用 fetch 下载该单个 URL。"
                )
        return None

    @staticmethod
    def _format_skipped_files(skipped: list[str]) -> str:
        if not skipped:
            return ""
        preview = ", ".join(skipped[:5])
        extra = f" 等 {len(skipped)} 个" if len(skipped) > 5 else ""
        return (
            f"\n[系统限制] 本任务仅允许 1 张图片，已忽略额外文件：{preview}{extra}"
        )

    @staticmethod
    def _track_playwright_context(tool_name: str, arguments: dict[str, Any]) -> str | None:
        name = (tool_name or "").strip().lower()
        if name != "browser_navigate":
            return None
        for key in ("url", "URL", "address", "href"):
            val = arguments.get(key)
            if val:
                return str(val).strip()
        return None

    @staticmethod
    def _format_organized_files(organized: list[dict[str, str]]) -> str:
        if not organized:
            return ""
        lines = ["", "[存储整理] 文件已自动归类到 data/mcp："]
        for item in organized:
            lines.append(f"  • {item.get('relative', item.get('to', ''))}")
        return "\n".join(lines)

    def get_config(self) -> dict[str, Any]:
        cfg = self._config
        return {
            "enabled": cfg.enabled,
            "use_in_chat": cfg.use_in_chat,
            "max_agent_steps": cfg.max_agent_steps,
            "tool_result_max_chars": cfg.tool_result_max_chars,
            "default_call_timeout": cfg.default_call_timeout,
            "preload_on_startup": cfg.preload_on_startup,
            "playwright_headless": is_playwright_headless(cfg),
            "playwright_browser": playwright_browser_channel(cfg),
            "sdk_available": self._sdk_available,
            "config_path": str(MCP_CONFIG_PATH),
            "mcp_storage_root": str(mcp_storage_root()),
            "mcp_storage_layout": "data/mcp/{网站}/{images|videos|audio|documents|archives|other}/{文件名}",
            "servers": [
                {
                    "id": s.id,
                    "name": s.name,
                    "enabled": s.enabled,
                    "transport": s.transport,
                    "command": s.command,
                    "args": s.args,
                    "url": s.url,
                    "tool_prefix": s.tool_prefix,
                    "connected": s.id in self._connections and not self._connections[s.id].error,
                    "error": self._connections[s.id].error if s.id in self._connections else "",
                    "tool_count": len(self._connections[s.id].tools)
                    if s.id in self._connections
                    else 0,
                }
                for s in cfg.servers
            ],
        }

    def sdk_ok(self) -> bool:
        return self._sdk_available

    def is_ready(self) -> bool:
        if not self._sdk_available or not self._config.enabled:
            return False
        return any(
            sid in self._connections and not self._connections[sid].error
            for sid in (s.id for s in self._config.servers if s.enabled)
        )

    def bootstrap(self) -> None:
        if not self._sdk_available:
            logger.warning("未安装 mcp 包，MCP 功能不可用。请: pip install mcp")
            return
        if not self._config.enabled or not self._config.preload_on_startup:
            return
        for server in self._config.servers:
            if server.enabled:
                try:
                    self.connect_server(server.id)
                except Exception as exc:
                    logger.warning("MCP 预连接 %s 失败: %s", server.id, exc)

    def shutdown(self) -> None:
        with self._lock:
            self._disconnect_all_unlocked(close_timeout=30.0)

    def _disconnect_all_unlocked(self, *, close_timeout: float = 8.0) -> None:
        """断开 MCP 连接。配置保存用较短超时，避免阻塞设置页 HTTP 请求。"""
        if not self._connections:
            return

        async def _close_all() -> None:
            for conn in list(self._connections.values()):
                try:
                    await conn.bridge.close()
                except Exception:
                    logger.exception("关闭 MCP 连接 %s", conn.server.id)

        try:
            run_on_bridge_owner(_close_all, timeout=close_timeout)
        except Exception:
            logger.exception("MCP 批量关闭失败（%.0fs 内未完成）", close_timeout)
        self._connections.clear()

    async def _async_connect(self, server: McpServerConfig) -> _LiveConnection:
        bridge = MCPBridge()
        transport = server.transport
        if transport == "stdio":
            if not server.command:
                raise ValueError(f"服务器 {server.id} 缺少 command")
            await bridge.connect_stdio(server.command, server.args, server.env or None)
        elif transport == "sse":
            if not server.url:
                raise ValueError(f"服务器 {server.id} 缺少 url")
            await bridge.connect_sse(server.url, server.headers or None)
        elif transport == "streamable_http":
            if not server.url:
                raise ValueError(f"服务器 {server.id} 缺少 url")
            await bridge.connect_streamable_http(server.url, server.headers or None)
        else:
            raise ValueError(f"不支持的 transport: {transport}")

        tools: list[McpToolInfo] = []
        for t in await bridge.list_tools():
            try:
                d = _tool_to_dict(t)
            except Exception:
                continue
            short = str(d.get("name") or "").strip()
            if not short:
                continue
            prefix = server.tool_prefix or ""
            reg = f"{prefix}{short}" if prefix else short
            tools.append(
                McpToolInfo(
                    server_id=server.id,
                    server_name=server.name,
                    name=short,
                    registered_name=reg,
                    description=str(d.get("description") or ""),
                    input_schema=d.get("inputSchema") if isinstance(d.get("inputSchema"), dict) else {},
                )
            )
        return _LiveConnection(server=server, bridge=bridge, tools=tools)

    def connect_server(self, server_id: str) -> dict[str, Any]:
        if not self._sdk_available:
            raise RuntimeError("未安装 Python 包 mcp，请执行: pip install mcp")
        if not self._config.enabled:
            raise RuntimeError("MCP 已在配置中禁用 (enabled=false)")

        server = get_server(self._config, server_id)
        if server is None:
            raise KeyError(f"未知 MCP 服务器: {server_id}")
        if not server.enabled:
            raise RuntimeError(f"MCP 服务器 {server_id} 已禁用")

        with self._lock:
            old = self._connections.pop(server_id, None)
            if old is not None:

                async def _close_old() -> None:
                    await old.bridge.close()

                try:
                    run_on_bridge_owner(_close_old, timeout=30.0)
                except Exception:
                    logger.debug("关闭旧 MCP 连接失败", exc_info=True)

        timeout = self._config.default_call_timeout

        def _make_connect() -> Any:
            return self._async_connect(server)

        try:
            conn = run_on_bridge_owner(_make_connect, timeout=timeout)
        except Exception as exc:
            with self._lock:
                self._connections[server_id] = _LiveConnection(
                    server=server, bridge=MCPBridge(), tools=[], error=str(exc)
                )
            raise

        with self._lock:
            self._connections[server_id] = conn
        return {
            "server_id": server_id,
            "name": server.name,
            "connected": True,
            "tool_count": len(conn.tools),
            "tools": [t.registered_name for t in conn.tools],
        }

    def list_tools(self, *, connect: bool = True) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self._config.enabled:
            for server in self._config.servers:
                if not server.enabled:
                    continue
                conn = self._connections.get(server.id)
                if conn is None or conn.error:
                    if connect:
                        try:
                            self.connect_server(server.id)
                            conn = self._connections.get(server.id)
                        except Exception as exc:
                            logger.warning("连接 MCP %s 失败: %s", server.id, exc)
                            continue
                    else:
                        continue
                if conn is None:
                    continue
                for t in conn.tools:
                    llm_name = llm_tool_name(t.server_id, t.name)
                    out.append(
                        {
                            "server_id": t.server_id,
                            "server_name": t.server_name,
                            "name": t.name,
                            "llm_name": llm_name,
                            "registered_name": t.registered_name,
                            "description": t.description,
                            "input_schema": t.input_schema,
                        }
                    )
        try:
            from pnn.launch_apps.service import launch_apps_service

            out.extend(launch_apps_service.list_tool_specs())
        except Exception as exc:
            logger.debug("本地快捷启动工具不可用: %s", exc)
        return out

    def tools_for_openai(self, *, connect: bool = True) -> list[dict[str, Any]]:
        """转为 OpenAI Chat Completions tools 格式。"""
        specs: list[dict[str, Any]] = []
        for t in self.list_tools(connect=connect):
            schema = t.get("input_schema")
            if not isinstance(schema, dict) or not schema:
                schema = {"type": "object", "properties": {}}
            desc = str(t.get("description") or "").strip()
            server_name = str(t.get("server_name") or t.get("server_id") or "")
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["llm_name"],
                        "description": f"[{server_name}] {desc}".strip(),
                        "parameters": schema,
                    },
                }
            )
        return specs

    def chat_enabled(self) -> bool:
        return bool(self._config.enabled and self._config.use_in_chat and self._sdk_available)

    def call_tool_by_llm_name(
        self,
        llm_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        server_id, tool_name = parse_llm_tool_name(llm_name)
        return self.call_tool(server_id=server_id, tool_name=tool_name, arguments=arguments)

    def call_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from pnn.launch_apps.config_store import (
            LAUNCH_TOOL_NAME,
            LOCAL_SERVER_ID,
            OPEN_FOLDER_TOOL_NAME,
            OPEN_URL_TOOL_NAME,
        )
        from pnn.launch_apps.service import launch_apps_service

        if server_id == LOCAL_SERVER_ID:
            if tool_name == LAUNCH_TOOL_NAME:
                text = launch_apps_service.call_launch_app(arguments)
                return {"server_id": server_id, "tool": tool_name, "result": text}
            if tool_name == OPEN_FOLDER_TOOL_NAME:
                text = launch_apps_service.call_open_folder(arguments)
                return {"server_id": server_id, "tool": tool_name, "result": text}
            if tool_name == OPEN_URL_TOOL_NAME:
                text = launch_apps_service.call_open_url(arguments)
                return {"server_id": server_id, "tool": tool_name, "result": text}

        if not self._sdk_available:
            raise RuntimeError("未安装 Python 包 mcp")
        with self._lock:
            conn = self._connections.get(server_id)
        if conn is None or conn.error:
            self.connect_server(server_id)
            with self._lock:
                conn = self._connections.get(server_id)
        if conn is None or conn.error:
            raise RuntimeError(f"MCP 服务器 {server_id} 未连接: {conn.error if conn else 'unknown'}")

        raw_name = tool_name
        prefix = conn.server.tool_prefix or ""
        if prefix and raw_name.startswith(prefix):
            raw_name = raw_name[len(prefix) :]

        bridge = conn.bridge
        timeout = self._config.default_call_timeout
        args = arguments or {}

        page_url = self._track_playwright_context(raw_name, args)
        if page_url:
            self._agent_page_url = page_url

        blocked = self._guard_playwright_download(
            raw_name,
            args,
            single_image=self._single_image_download,
            images_saved=self._agent_images_saved,
        )
        if blocked:
            if self._single_image_download and self._agent_images_saved >= 1:
                purge_staging_images()
            return {
                "server_id": server_id,
                "tool": raw_name,
                "result": blocked,
            }

        async def _call() -> str:
            return await bridge.call_tool(raw_name, args)

        def _make() -> Any:
            return _call()

        text = run_on_bridge_owner(_make, timeout=timeout)
        result: dict[str, Any] = {
            "server_id": server_id,
            "tool": raw_name,
            "result": text,
        }

        if server_id == PLAYWRIGHT_SERVER_ID and raw_name.lower() in (
            "browser_run_code",
            "browser_take_screenshot",
            "browser_navigate",
        ):
            quota = self._remaining_image_quota()
            organized, skipped = organize_staging(
                site_url=self._agent_page_url,
                max_images=quota,
            )
            if organized:
                img_saved = sum(1 for x in organized if x.get("category") == "images")
                self._agent_images_saved += img_saved
                result["organized_files"] = organized
                suffix = self._format_organized_files(organized)
                if skipped:
                    suffix += self._format_skipped_files(skipped)
                result["result"] = text + suffix
            elif skipped:
                result["result"] = text + self._format_skipped_files(skipped)
            elif self._single_image_download and self._agent_images_saved >= 1:
                purged = purge_staging_images()
                if purged:
                    result["result"] = (
                        text
                        + f"\n[系统限制] 已忽略暂存区 {purged} 个额外图片文件（本任务仅允许 1 张）。"
                    )

        return result


mcp_service = McpService()
