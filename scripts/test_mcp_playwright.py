"""试连 Playwright MCP：列出工具。用法: python scripts/test_mcp_playwright.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from pnn.mcp.config_store import MCP_CONFIG_PATH, load_mcp_config
    from pnn.mcp.service import mcp_service

    cfg = load_mcp_config()
    print(f"MCP 配置: {MCP_CONFIG_PATH}")
    print(f"enabled={cfg.enabled}, servers={[s.id for s in cfg.servers]}")

    if not mcp_service.sdk_ok():
        print("错误: 未安装 mcp 包。请执行: pip install mcp")
        sys.exit(1)

    pw = next((s for s in cfg.servers if s.id == "playwright"), cfg.servers[0] if cfg.servers else None)
    if pw is None:
        print("错误: mcp.json 中无可用 server")
        sys.exit(1)

    print(f"\n正在连接 {pw.id} ({pw.command} {' '.join(pw.args)}) …")
    print("（首次可能下载 @playwright/mcp 与浏览器，约 1–3 分钟）\n")

    try:
        info = mcp_service.connect_server(pw.id)
    except Exception as exc:
        print(f"连接失败: {exc}")
        sys.exit(2)

    print(f"已连接: {info}")
    tools = mcp_service.list_tools(connect=False)
    print(f"\n共 {len(tools)} 个工具:")
    for t in tools[:15]:
        print(f"  - {t['registered_name']}: {t['description'][:80]}")
    if len(tools) > 15:
        print(f"  … 另有 {len(tools) - 15} 个")

    mcp_service.shutdown()
    print("\n完成。")


if __name__ == "__main__":
    main()
