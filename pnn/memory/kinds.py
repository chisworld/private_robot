"""记忆类型元数据：展示标签、颜色、说明。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryKindMeta:
    kind: str
    label: str
    short: str
    description: str
    color: str
    sort: int


KIND_CATALOG: tuple[MemoryKindMeta, ...] = (
    MemoryKindMeta(
        "fact",
        "事实",
        "fact",
        "长期稳定信息：称呼、喜好、身份、习惯等",
        "#818cf8",
        10,
    ),
    MemoryKindMeta(
        "event",
        "事件",
        "event",
        "发生过的重要经历：赌局、旅行、吵架和好等",
        "#f59e0b",
        20,
    ),
    MemoryKindMeta(
        "emotion",
        "情绪",
        "emotion",
        "持续一段时间的心情或状态",
        "#c084fc",
        30,
    ),
    MemoryKindMeta(
        "dialogue",
        "对话",
        "dialogue",
        "完整一轮用户与角色的原文对话",
        "#34d399",
        40,
    ),
    MemoryKindMeta(
        "diary",
        "日记",
        "diary",
        "一次会话结束时的合并摘要",
        "#a78bfa",
        50,
    ),
    MemoryKindMeta(
        "chat",
        "摘要",
        "chat",
        "旧式一句摘要（逐步淘汰）",
        "#64748b",
        60,
    ),
)

KIND_BY_ID: dict[str, MemoryKindMeta] = {m.kind: m for m in KIND_CATALOG}

ALL_KINDS: tuple[str, ...] = tuple(m.kind for m in KIND_CATALOG)


def kind_meta(kind: str) -> MemoryKindMeta:
    k = (kind or "fact").strip().lower() or "fact"
    return KIND_BY_ID.get(k, MemoryKindMeta(k, k, k, "", "#8e8e93", 99))


def kind_label(kind: str) -> str:
    return kind_meta(kind).label


def memory_kind_choices() -> list[tuple[str, str]]:
    """(value, label) for UI filters; empty value = 全部."""
    return [("", "全部分类")] + [(m.kind, m.label) for m in KIND_CATALOG]


def format_kind_stats(counts: dict[str, int]) -> str:
    parts: list[str] = []
    total = sum(counts.values())
    for meta in KIND_CATALOG:
        n = int(counts.get(meta.kind, 0))
        if n:
            parts.append(f"{meta.label} {n}")
    if not parts:
        return "记忆库为空"
    return f"共 {total} 条 · " + " · ".join(parts)
