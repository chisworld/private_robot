"""MCP 服务配置（data/config/mcp.json）。"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pnn.core.config_cache import MtimeJsonConfigCache
from pnn.core.paths import CONFIG_DIR, CONFIG_TEMPLATES_DIR

logger = logging.getLogger(__name__)

MCP_CONFIG_PATH = CONFIG_DIR / "mcp.json"
_MCP_TEMPLATE = CONFIG_TEMPLATES_DIR / "mcp.json.example"

# Agent 每轮 = LLM 思考 + 一次或多次 MCP 工具调用；浏览器寻图常需 10+ 轮
MAX_AGENT_STEPS_LIMIT = 40
DEFAULT_MAX_AGENT_STEPS = 12


@dataclass
class McpServerConfig:
    id: str
    name: str = ""
    enabled: bool = True
    transport: str = "stdio"  # stdio | sse | streamable_http
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    tool_prefix: str = ""


@dataclass
class McpConfig:
    enabled: bool = True
    use_in_chat: bool = True
    max_agent_steps: int = DEFAULT_MAX_AGENT_STEPS
    tool_result_max_chars: int = 12000
    default_call_timeout: float = 120.0
    preload_on_startup: bool = False
    servers: list[McpServerConfig] = field(default_factory=list)


_mcp_config_cache = MtimeJsonConfigCache[McpConfig]()


def _clamp_int(v: object, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _parse_server(raw: object) -> McpServerConfig | None:
    if not isinstance(raw, dict):
        return None
    sid = str(raw.get("id") or "").strip()
    if not sid:
        return None
    args_raw = raw.get("args")
    args = [str(x) for x in args_raw] if isinstance(args_raw, list) else []
    headers_raw = raw.get("headers")
    headers = (
        {str(k): str(v) for k, v in headers_raw.items()}
        if isinstance(headers_raw, dict)
        else {}
    )
    env_raw = raw.get("env")
    env = {str(k): str(v) for k, v in env_raw.items()} if isinstance(env_raw, dict) else {}
    return McpServerConfig(
        id=sid,
        name=str(raw.get("name") or sid),
        enabled=bool(raw.get("enabled", True)),
        transport=str(raw.get("transport") or "stdio").strip().lower(),
        command=str(raw.get("command") or "").strip(),
        args=args,
        url=str(raw.get("url") or "").strip(),
        headers=headers,
        env=env,
        tool_prefix=str(raw.get("tool_prefix") or ""),
    )


def _ensure_config_file() -> None:
    if MCP_CONFIG_PATH.is_file():
        return
    MCP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _MCP_TEMPLATE.is_file():
        shutil.copy(_MCP_TEMPLATE, MCP_CONFIG_PATH)
        logger.info("已生成默认 MCP 配置: %s", MCP_CONFIG_PATH)
    else:
        save_mcp_config(McpConfig(servers=[_default_playwright_server()]))


PLAYWRIGHT_SERVER_ID = "playwright"
PLAYWRIGHT_BROWSER_EDGE = "msedge"
_BROWSER_ARG_PREFIX = "--browser="


def playwright_server(cfg: McpConfig) -> McpServerConfig | None:
    for s in cfg.servers:
        if s.id == PLAYWRIGHT_SERVER_ID:
            return s
    return None


def playwright_browser_channel(cfg: McpConfig) -> str:
    s = playwright_server(cfg)
    if not s:
        return PLAYWRIGHT_BROWSER_EDGE
    for arg in s.args:
        if arg.startswith(_BROWSER_ARG_PREFIX):
            return arg.split("=", 1)[1].strip() or PLAYWRIGHT_BROWSER_EDGE
    env_val = str(s.env.get("PLAYWRIGHT_MCP_BROWSER", "")).strip()
    return env_val or PLAYWRIGHT_BROWSER_EDGE


def ensure_playwright_browser(cfg: McpConfig, browser: str = PLAYWRIGHT_BROWSER_EDGE) -> None:
    """MCP 浏览器搜索默认使用本机 Edge（--browser=msedge）。"""
    s = playwright_server(cfg)
    if not s:
        return
    channel = (browser or PLAYWRIGHT_BROWSER_EDGE).strip() or PLAYWRIGHT_BROWSER_EDGE
    args = [a for a in s.args if not a.startswith(_BROWSER_ARG_PREFIX)]
    args.append(f"{_BROWSER_ARG_PREFIX}{channel}")
    s.args = args
    env = dict(s.env)
    env["PLAYWRIGHT_MCP_BROWSER"] = channel
    s.env = env


def is_playwright_headless(cfg: McpConfig) -> bool:
    s = playwright_server(cfg)
    if not s:
        return False
    if str(s.env.get("PLAYWRIGHT_MCP_HEADLESS", "")).lower() in ("1", "true", "yes"):
        return True
    return "--headless" in s.args


def set_playwright_headless(cfg: McpConfig, headless: bool) -> None:
    s = playwright_server(cfg)
    if not s:
        return
    args = [a for a in s.args if a != "--headless"]
    env = dict(s.env)
    env.pop("PLAYWRIGHT_MCP_HEADLESS", None)
    if headless:
        args.append("--headless")
    s.args = args
    s.env = env


def ensure_playwright_output_dir(cfg: McpConfig) -> None:
    """Playwright 截图/下载暂存到 data/mcp/_staging，随后由 storage 自动归类。"""
    from pnn.mcp.storage import ensure_mcp_storage_layout, mcp_staging_dir

    ensure_mcp_storage_layout()
    out = str(mcp_staging_dir())
    s = playwright_server(cfg)
    if not s:
        return
    args = list(s.args)
    flag = "--output-dir"
    if flag in args:
        idx = args.index(flag)
        if idx + 1 < len(args):
            args[idx + 1] = out
        else:
            args.append(out)
    else:
        args.extend([flag, out])
    s.args = args
    env = dict(s.env)
    env["PLAYWRIGHT_MCP_OUTPUT_DIR"] = out
    s.env = env


def _default_playwright_server() -> McpServerConfig:
    return McpServerConfig(
        id="playwright",
        name="Playwright 浏览器",
        enabled=True,
        transport="stdio",
        command="npx",
        args=["-y", "@playwright/mcp@latest", f"{_BROWSER_ARG_PREFIX}{PLAYWRIGHT_BROWSER_EDGE}"],
        env={"PLAYWRIGHT_MCP_BROWSER": PLAYWRIGHT_BROWSER_EDGE},
        tool_prefix="",
    )


def _load_mcp_config_uncached() -> McpConfig:
    from pnn.mcp.code_workspace import ensure_filesystem_server

    _ensure_config_file()
    try:
        raw = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 MCP 配置失败，使用默认 Playwright: %s", exc)
        cfg = McpConfig(servers=_default_servers())
        ensure_playwright_browser(cfg)
        ensure_playwright_output_dir(cfg)
        ensure_filesystem_server(cfg)
        return cfg

    if not isinstance(raw, dict):
        cfg = McpConfig(servers=_default_servers())
        ensure_playwright_browser(cfg)
        ensure_playwright_output_dir(cfg)
        ensure_filesystem_server(cfg)
        return cfg

    servers: list[McpServerConfig] = []
    for item in raw.get("servers") or []:
        parsed = _parse_server(item)
        if parsed is not None:
            servers.append(parsed)
    if not servers:
        servers = _default_servers()

    timeout = raw.get("default_call_timeout", 120.0)
    try:
        timeout_f = float(timeout)
    except (TypeError, ValueError):
        timeout_f = 120.0

    cfg = McpConfig(
        enabled=bool(raw.get("enabled", True)),
        use_in_chat=bool(raw.get("use_in_chat", True)),
        max_agent_steps=_clamp_int(
            raw.get("max_agent_steps"),
            DEFAULT_MAX_AGENT_STEPS,
            1,
            MAX_AGENT_STEPS_LIMIT,
        ),
        tool_result_max_chars=_clamp_int(raw.get("tool_result_max_chars"), 12000, 500, 50000),
        default_call_timeout=max(5.0, min(600.0, timeout_f)),
        preload_on_startup=bool(raw.get("preload_on_startup", False)),
        servers=servers,
    )
    ensure_playwright_browser(cfg)
    ensure_playwright_output_dir(cfg)
    ensure_filesystem_server(cfg)
    return cfg


def load_mcp_config() -> McpConfig:
    return _mcp_config_cache.get(MCP_CONFIG_PATH, _load_mcp_config_uncached)


def _default_servers() -> list[McpServerConfig]:
    from pnn.mcp.code_workspace import default_filesystem_server

    return [_default_playwright_server(), default_filesystem_server()]


def save_mcp_config(config: McpConfig) -> None:
    MCP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": config.enabled,
        "use_in_chat": config.use_in_chat,
        "max_agent_steps": config.max_agent_steps,
        "tool_result_max_chars": config.tool_result_max_chars,
        "default_call_timeout": config.default_call_timeout,
        "preload_on_startup": config.preload_on_startup,
        "servers": [asdict(s) for s in config.servers],
    }
    MCP_CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _mcp_config_cache.invalidate()


def get_server(config: McpConfig, server_id: str) -> McpServerConfig | None:
    sid = (server_id or "").strip()
    for s in config.servers:
        if s.id == sid:
            return s
    return None


def patch_mcp_config(
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
    """直接写入 data/config/mcp.json（桌宠侧 fallback，不依赖 API 进程）。"""
    cfg = load_mcp_config()
    if enabled is not None:
        cfg.enabled = bool(enabled)
    if use_in_chat is not None:
        cfg.use_in_chat = bool(use_in_chat)
    if max_agent_steps is not None:
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
    ensure_playwright_browser(cfg)
    ensure_playwright_output_dir(cfg)
    save_mcp_config(cfg)
    return cfg
