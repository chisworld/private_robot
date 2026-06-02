"""14酱 模型额外表情（model3.json 未内嵌，需 LoadExtraExpression）。"""

from __future__ import annotations

# 启动时优先加载（默认脸、水印）
EXPRESSION_FILES_PRIORITY: list[tuple[str, str]] = [
    ("我也要死吗", "我也要死吗.exp3.json"),
    ("黑脸", "黑脸.exp3.json"),
    ("关闭水印", "关闭水印.exp3.json"),
    ("脸红", "脸红.exp3.json"),
    ("笑嘻", "笑嘻.exp3.json"),
]

# 其余表情延后加载，加快首屏
EXPRESSION_FILES_DEFERRED: list[tuple[str, str]] = [
    ("爱心眼", "爱心眼.exp3.json"),
    ("生气眉毛", "生气眉毛.exp3.json"),
    ("晕晕眼", "晕晕眼.exp3.json"),
    ("歪嘴", "歪嘴.exp3.json"),
    ("流汗", "流汗.exp3.json"),
    ("眼泪1", "眼泪1.exp3.json"),
    ("眼泪2", "眼泪2.exp3.json"),
    ("比耶", "比耶.exp3.json"),
    ("X嘴", "X嘴.exp3.json"),
    ("吐舌嘴", "吐舌嘴.exp3.json"),
    ("口水", "口水.exp3.json"),
    ("颤抖嘴", "颤抖嘴.exp3.json"),
    ("黑眼圈", "黑眼圈.exp3.json"),
    ("组合1 生气", "组合1 生气.exp3.json"),
    ("组合2 爱心", "组合2 爱心.exp3.json"),
    ("组合3 晕晕", "组合3 晕晕.exp3.json"),
    ("组合4 比耶晕晕", "组合4 比耶晕晕.exp3.json"),
    ("组合5", "组合5.exp3.json"),
]

EXPRESSION_FILES: list[tuple[str, str]] = (
    EXPRESSION_FILES_PRIORITY + EXPRESSION_FILES_DEFERRED
)


def _load_expression_batch(model, root, files: list[tuple[str, str]]) -> list[str]:
    loaded: list[str] = []
    for name, filename in files:
        path = root / filename
        if not path.is_file():
            continue
        try:
            model.LoadExtraExpression(name, str(path.resolve()))
            loaded.append(name)
        except Exception:
            pass
    return loaded


def load_model_expressions(
    model,
    model_dir,
    *,
    priority_only: bool = False,
) -> list[str]:
    """加载目录下 exp3 表情，返回成功加载的名称列表。"""
    from pathlib import Path

    root = Path(model_dir)
    loaded = _load_expression_batch(model, root, EXPRESSION_FILES_PRIORITY)
    if not priority_only:
        loaded.extend(_load_expression_batch(model, root, EXPRESSION_FILES_DEFERRED))
    return loaded


def load_deferred_model_expressions(model, model_dir) -> list[str]:
    from pathlib import Path

    return _load_expression_batch(model, Path(model_dir), EXPRESSION_FILES_DEFERRED)
