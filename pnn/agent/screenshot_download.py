"""截图寻图下载：Agent / LLM 共用任务约束（只下一张匹配图）。"""

from __future__ import annotations

from pnn.mcp.storage import mcp_storage_root, mcp_staging_dir

_staging = mcp_staging_dir()
_root = mcp_storage_root()

# 注入用户消息（LLM 侧）
SCREENSHOT_DOWNLOAD_TASK_BODY = (
    "【任务】用户在截图里圈定/指定了「这一张」目标图，"
    "请在用户给出的网站中找到与之最匹配的那一张并下载。\n"
    "【硬性限制】\n"
    f"• 只下载 1 张图片，先保存到 Playwright 暂存目录 {_staging}\n"
    f"• 系统会自动整理到 {_root}/{{网站}}/images/{{语义化文件名}}.png\n"
    "• 禁止批量下载、禁止 for 循环遍历全部 img、禁止下载页面里所有游戏截图/画廊图\n"
    "• 禁止 querySelectorAll('img') / document.images 循环 fetch\n"
    "• browser_take_screenshot 只能用来查看页面，不能代替下载原图文件\n"
    "• 若页面有多张相似图，只选与「截图分析」最接近的 1 张，其余一律不下载\n"
    "• 系统会在保存第 1 张图片后拒绝后续下载请求，请勿重试批量脚本\n"
    "• 文件名用角色名/作品名等有意义名称，不要用 matched.png\n"
    "【推荐步骤】\n"
    "1. 打开网站并搜索/进入相关页面\n"
    "2. browser_snapshot 定位最匹配的那一张（看 alt、标题、相邻文字）\n"
    "3. 取得该图单个原图 URL（不是画廊列表页），用 browser_run_code 仅 fetch 这一 URL 并写入暂存目录\n"
    "4. 完成后确认仅新增这一张文件，并告知用户最终归类路径；立即停止，不要继续下载"
)

SCREENSHOT_TASK_MARKERS: tuple[str, ...] = (
    "【用户附带的截图分析】",
    "【任务】用户在截图里",
)


def is_screenshot_download_task(text: str) -> bool:
    """用户消息是否来自「附截图 + 指定网站下载」任务。"""
    body = (text or "").strip()
    if not body:
        return False
    return any(marker in body for marker in SCREENSHOT_TASK_MARKERS)


def looks_like_bulk_image_download(code: str) -> bool:
    """browser_run_code 脚本是否疑似批量下载页面图片。"""
    c = (code or "").strip().lower()
    if not c:
        return False
    loop_markers = (
        "queryselectorall",
        "getelementsbytagname('img'",
        'getelementsbytagname("img"',
        "document.images",
        ".foreach(",
        " for (",
        " for(",
        " for await",
        " for of ",
        " for(const",
        " for(let",
        " for(var",
        ".map(",
        "downloadall",
        "allimages",
        "all_images",
    )
    fetch_markers = (
        "fetch(",
        "arraybuffer",
        "writefile",
        "write(",
        "download",
        "blob",
        "createobjecturl",
    )
    if not any(m in c for m in fetch_markers):
        return False
    return any(m in c for m in loop_markers)


def build_screenshot_download_agent_section(report_step: str) -> str:
    """构建截图下载 Agent 提示（勿对整段 .format，避免 {网站} 占位符冲突）。"""
    return (
        "【截图寻图下载】当用户附带了「截图分析」并指定网站时：\n"
        "★ 核心：用户要的是截图里那「一张」图，不是页面全部图片。\n"
        f"★ 硬性限制：只能下载 1 张图片；暂存于 {_staging}，"
        f"自动归类到 {_root}/{{网站}}/images/{{文件名}}。\n"
        "  禁止：批量下载、循环所有 img、querySelectorAll 遍历、下载整个截图画廊。\n"
        "  系统会在保存第 1 张图片后自动拒绝后续下载工具调用。\n"
        "步骤：\n"
        "1. browser_navigate 打开用户指定网站；必要时搜索关键词（来自截图分析）。\n"
        "2. browser_snapshot 浏览结果，根据截图分析中的角色/作品/配色/文字，"
        "锁定最匹配的「单张」候选（不是一组图）。\n"
        "3. 取得该图原图 URL，用 browser_run_code 仅 fetch 这一 URL 到暂存目录（单文件、语义化文件名）。\n"
        "   browser_take_screenshot 仅用于调试查看页面，不可作为交付物。\n"
        "4. 若有多张相似图，对比后只下载最接近截图描述的那 1 张；下载完成后立即停止，"
        "不要继续下载其他图片。\n"
        f"5. {report_step}"
    )


# 兼容旧引用
SCREENSHOT_DOWNLOAD_AGENT_SECTION = build_screenshot_download_agent_section("{report_step}")
