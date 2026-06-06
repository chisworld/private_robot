"""桌宠 Agent：通过 filesystem MCP 读写项目代码。"""

from __future__ import annotations

import re

from pnn.agent.project_map import build_project_map
from pnn.agent.skill_loader import ensure_user_skills_dir, load_agent_skills_text
from pnn.core.paths import PROJECT_ROOT

_CODE_INTENT_RE = re.compile(
    r"(改|修|写|加|删|创建|阅读|读|查看|打开|搜索|查找|重构|实现|修复|bug|代码|"
    r"\.py|\.ts|\.tsx|\.json|\.md|文件|函数|类|模块|import|def |class )",
    re.IGNORECASE,
)

# Agent 改代码时的参数_boost（相对 llm.json 默认值）
CODE_EDIT_MIN_MAX_TOKENS = 8192
CODE_EDIT_TEMPERATURE = 0.2
CODE_EDIT_TOOL_RESULT_CHARS = 32000


def looks_like_code_edit_task(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    try:
        from pnn.core.weather_query import user_asks_weather

        if user_asks_weather(raw):
            return False
    except Exception:
        pass
    if _CODE_INTENT_RE.search(raw):
        return True
    return any(tok in raw for tok in ("/", "\\", ".py", "pnn/", "server/"))


def boost_max_tokens(base: int) -> int:
    return max(int(base or 1024), CODE_EDIT_MIN_MAX_TOKENS)


def boost_tool_result_cap(base: int) -> int:
    return max(int(base or 12000), CODE_EDIT_TOOL_RESULT_CHARS)


def code_edit_temperature(base: float) -> float:
    """改代码时用更低温度，减少胡乱发挥。"""
    return min(float(base or 0.7), CODE_EDIT_TEMPERATURE)


def build_agent_code_edit_instructions(*, include_map: bool = True) -> str:
    root = PROJECT_ROOT.resolve()
    root_posix = root.as_posix()
    parts = [
        "【项目代码编辑】当用户要求修改、阅读、创建本项目代码时，使用 filesystem MCP：",
        f"• 工作区根目录：{root_posix}",
        "• 工具前缀 filesystem__；推荐顺序：",
        "  1) search_files / list_directory 定位路径",
        "  2) read_text_file 读取完整相关片段（大文件分段读）",
        "  3) edit_file 做局部替换（优先，避免覆盖整文件）",
        "  4) write_file 仅用于新建小文件或整文件重写",
        "  5) 改后再 read_text_file 核对关键片段",
        "• 路径使用相对工作区的 posix 路径，如 pnn/mcp/storage.py",
        "• 禁止：访问工作区外路径；读/写 .env、含 api_key/secret 的配置；models/ 权重",
        "• 禁止：Shell、安装依赖、跑测试（只改文件）",
        "• 多文件改动：逐个文件 edit，每改一个简要自检；改完列出变更清单",
        "• 不确定时先 search_files，不要编造不存在的模块名",
    ]
    if include_map:
        parts.append("")
        parts.append(build_project_map())
    skills = load_agent_skills_text(code_edit_only=True)
    if skills:
        parts.append("")
        parts.append(skills)
    ensure_user_skills_dir()
    return "\n".join(parts)
