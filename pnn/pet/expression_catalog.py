"""从模型目录扫描 Live2D 表情名（.exp3.json 文件名）。"""

from __future__ import annotations

from pathlib import Path


def _discover_exclude_names(model_dir: Path) -> frozenset[str]:
    """自动发现应排除的表情名（水印类等非情绪表达式）。"""
    names: set[str] = set()
    patterns = ("*水印*.exp3.json", "关闭水印.exp3.json")
    for pattern in patterns:
        for path in model_dir.glob(pattern):
            name = path.name
            if name.endswith(".exp3.json"):
                name = name[: -len(".exp3.json")]
            names.add(name)
    return frozenset(names) if names else frozenset({"关闭水印"})


def _name_from_exp3_file(path: Path) -> str:
    """笑嘻.exp3.json → 笑嘻（Path.stem 会得到 笑嘻.exp3）。"""
    name = path.name
    if name.endswith(".exp3.json"):
        return name[: -len(".exp3.json")]
    return path.stem


def discover_expression_names(model_dir: Path | None = None) -> list[str]:
    from pnn.pet.paths import DEFAULT_EXPRESSION, MODEL_DIR

    root = model_dir or MODEL_DIR
    if not root.is_dir():
        return [DEFAULT_EXPRESSION]
    exclude = _discover_exclude_names(root)
    names = sorted(
        _name_from_exp3_file(p)
        for p in root.glob("*.exp3.json")
        if _name_from_exp3_file(p) not in exclude
    )
    return names or [DEFAULT_EXPRESSION]


def build_llm_expression_instruction(names: list[str]) -> str:
    """注入 LLM 的系统说明：每句句首加【表情:名称】标签。"""
    from pnn.pet.paths import DEFAULT_EXPRESSION

    lines = "\n".join(f"- {n}" for n in names)
    return (
        "【Live2D 表情标注 — 必须遵守，用户界面不会显示这些标签】\n"
        "在每一段完整句子（以 。！？!? 或换行 结束）的**最开头**，"
        "插入且仅插入一个标签，格式严格为：【表情:名称】\n"
        "其中「名称」必须从下列列表中逐字复制，不得自造、不得加空格或英文：\n"
        f"{lines}\n"
        "根据该句语气与情绪选择最贴切的一项；下一句可换用不同表情。\n"
        "标签只出现在句首，正文与朗读内容中不得出现「表情」「【】」等说明字样。\n"
        f"若难以判断，使用【表情:{DEFAULT_EXPRESSION}】。"
    )
