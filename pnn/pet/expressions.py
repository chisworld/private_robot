"""Live2D 模型额外表情（自动发现模型目录下的 .exp3.json 文件）。"""

from __future__ import annotations

from pathlib import Path


def _default_priority_names() -> set[str]:
    from pnn.pet.paths import DEFAULT_EXPRESSION, HIDE_WATERMARK_EXPRESSION

    return {DEFAULT_EXPRESSION, HIDE_WATERMARK_EXPRESSION}


def _discover_exp3_files(model_dir: Path) -> list[tuple[str, str]]:
    """Discover all .exp3.json files, returning [(name, filename), ...]."""
    pairs: list[tuple[str, str]] = []
    for path in sorted(model_dir.glob("*.exp3.json")):
        name = path.name
        if name.endswith(".exp3.json"):
            expr_name = name[: -len(".exp3.json")]
        else:
            expr_name = path.stem
        pairs.append((expr_name, path.name))
    return pairs


def _prioritize_expressions(
    pairs: list[tuple[str, str]],
    *,
    priority_names: set[str] | None = None,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Split into priority (must-load-first) and deferred."""
    preferred = priority_names or _default_priority_names()
    priority = [(n, f) for n, f in pairs if n in preferred]
    deferred = [(n, f) for n, f in pairs if n not in preferred]
    return priority, deferred


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
    """Load all .exp3.json expressions from the model directory."""
    root = Path(model_dir)
    all_pairs = _discover_exp3_files(root)
    priority_pairs, deferred_pairs = _prioritize_expressions(all_pairs)

    loaded = _load_expression_batch(model, root, priority_pairs)
    if not priority_only:
        loaded.extend(_load_expression_batch(model, root, deferred_pairs))
    return loaded


def load_deferred_model_expressions(model, model_dir) -> list[str]:
    root = Path(model_dir)
    all_pairs = _discover_exp3_files(root)
    _, deferred_pairs = _prioritize_expressions(all_pairs)
    return _load_expression_batch(model, root, deferred_pairs)
