"""桌宠 Agent：通过 filesystem MCP 读写项目代码。"""

from __future__ import annotations

import re
from pathlib import Path

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
    if "作业" in raw or r"D:\Project\作业" in raw or r"D:/Project/作业" in raw:
        return True
    return any(tok in raw for tok in ("/", "\\", ".py", "pnn/", "server/"))


def boost_max_tokens(base: int) -> int:
    return max(int(base or 1024), CODE_EDIT_MIN_MAX_TOKENS)


def boost_tool_result_cap(base: int) -> int:
    return max(int(base or 12000), CODE_EDIT_TOOL_RESULT_CHARS)


def code_edit_temperature(base: float) -> float:
    """改代码时用更低温度，减少胡乱发挥。"""
    return min(float(base or 0.7), CODE_EDIT_TEMPERATURE)


_PROJECT_SEARCH_RE = re.compile(
    r"(?:"
    r"(?:帮(?:我|你在|帮忙)?|请|能不能|可以)?(?:在)?(?:本)?"
    r"(?:项目|代码库|仓库|repo|工程|codebase|workspace|工作区|源码|代码里|项目里|仓库里)"
    r".{0,20}(?:找|搜|查|定位|检索|浏览|看看|有没有|是否存在|在哪|哪里|哪儿)"
    r"|(?:找|搜|查|定位|检索|翻|扫|看看).{0,24}"
    r"(?:文件|代码|模块|函数|类|配置|目录|路径|源码|脚本|组件|接口|定义)"
    r"|(?:哪个|哪份|哪里|哪儿|在哪).{0,16}(?:文件|模块|函数|类|代码|配置).{0,16}"
    r"(?:有|包含|定义|写|放|实现|声明)?"
    r"|(?:有没有|是否存在|有没有叫|有没有名为).{0,32}(?:文件|模块|函数|类|代码)"
    r"|(?:全文)?(?:搜索|检索|查找).{0,16}(?:项目|代码|仓库|文件|目录)"
    r"|(?:grep|rg|ripgrep|glob).{0,16}(?:一下|项目|代码|文件)?"
    r"|search_files|list_directory|read_text_file|directory_tree|get_file_info"
    r"|\S+\.(?:py|ts|tsx|js|jsx|json|md|yaml|yml|toml|ini|cfg|txt|vue|go|rs|java|kt|cs|cpp|h)\b"
    r".{0,12}(?:在哪|哪里|哪儿|路径|文件|位置|定义)"
    r"|(?:文件|模块|代码|函数|类).{0,10}(?:名叫|叫|名为|叫做)\s*\S+"
    r")",
    re.IGNORECASE,
)


def looks_like_project_search_task(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    return bool(_PROJECT_SEARCH_RE.search(raw))


def build_agent_code_edit_instructions(*, include_map: bool = True) -> str:
    from pnn.mcp.code_workspace import list_filesystem_workspace_roots

    roots = list_filesystem_workspace_roots()
    root_lines = "\n".join(f"  - {Path(r).as_posix()}" for r in roots)
    parts = [
        "【项目代码编辑】当用户要求修改、阅读、创建代码时，使用 filesystem MCP：",
        f"• 可读写的工作区根目录（共 {len(roots)} 个）：",
        root_lines,
        "• 工具前缀 filesystem__；推荐顺序：",
        "  1) search_files / list_directory 定位路径",
        "  2) read_text_file 读取完整相关片段（大文件分段读）",
        "  3) edit_file 做局部替换（优先，避免覆盖整文件）",
        "  4) write_file 仅用于新建小文件或整文件重写",
        "  5) 改后再 read_text_file 核对关键片段",
        "• 路径可用相对某一根目录的 posix 路径（如 pnn/mcp/storage.py），"
        "或用户给出的绝对路径（如 D:/Project/作业/菌子接接乐/菌子接接乐.py）",
        "• 额外目录（如 D:/Project/作业）与主项目并列可访问，不算「在项目外」",
        "• 用户作业/课程项目在「作业」等额外目录下时，直接读写该目录内文件，勿拒绝",
        "• 用户给出绝对路径且落在上述根目录内时，必须先 read_text_file，禁止口头说无法访问",
        "• 若系统消息已「代码文件·已预读」，直接基于该内容回答，勿重复声称无法读取",
        "• 修改：read_text_file → edit_file；新建小文件：write_file",
        "• 禁止：访问上述根目录之外的路径；读/写 .env、含 api_key/secret 的配置；models/ 权重",
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
