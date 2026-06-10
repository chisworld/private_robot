"""从快捷方式路径生成白名单条目。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_LAUNCHABLE = {".exe", ".bat", ".cmd", ".com", ".lnk"}


def is_launchable_path(path: str | Path) -> bool:
    p = Path(str(path or "").strip())
    if not p.is_file():
        return False
    return p.suffix.lower() in _LAUNCHABLE


def label_from_path(path: Path) -> str:
    stem = path.stem
    if stem.lower() == "desktop" or not stem.strip():
        return path.name
    # 去掉常见后缀词
    for suffix in (" - 快捷方式", " Shortcut"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem.strip() or path.name


def slug_from_label(label: str, *, existing: set[str] | None = None) -> str:
    raw = (label or "").strip()
    ascii_slug = re.sub(r"[^\w]+", "_", raw.lower()).strip("_")
    if ascii_slug and ascii_slug.isascii() and len(ascii_slug) >= 2:
        base = ascii_slug[:32]
    else:
        base = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    taken = {x.lower() for x in (existing or set())}
    candidate = base
    n = 2
    while candidate.lower() in taken:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def normalize_match_text(text: str) -> str:
    """匹配用：全角标点、尾部符号归一化。"""
    raw = (text or "").strip().lower()
    if not raw:
        return ""
    table = str.maketrans("！？：；，．", "!?:;,.")
    raw = raw.translate(table)
    raw = re.sub(r"[!?.。、，!?]+$", "", raw)
    return re.sub(r"\s+", "", raw)


_GENERIC_APP_IDS = frozenset({"game", "app", "program", "exe"})


def ensure_unique_app_ids(
    apps: list,
    *,
    entry_type: type | None = None,
) -> tuple[list, bool]:
    """为重复或过于笼统的 id 生成唯一 slug（避免 resolve_app('game') 误启动第一项）。"""
    from dataclasses import replace

    from pnn.launch_apps.config_store import LaunchAppEntry

    cls = entry_type or LaunchAppEntry
    counts: dict[str, int] = {}
    for app in apps:
        key = (getattr(app, "id", "") or "").strip().lower()
        if key:
            counts[key] = counts.get(key, 0) + 1

    seen: set[str] = set()
    out: list = []
    changed = False
    for app in apps:
        app_id = (getattr(app, "id", "") or "").strip()
        key = app_id.lower()
        label = (getattr(app, "label", "") or "").strip()
        path = (getattr(app, "path", "") or "").strip()
        needs_new = (
            not key
            or counts.get(key, 0) > 1
            or key in _GENERIC_APP_IDS
            or key in seen
        )
        if not needs_new:
            seen.add(key)
            out.append(app)
            continue
        stem = label or (Path(path).stem if path else "app")
        new_id = slug_from_label(stem, existing=seen)
        seen.add(new_id.lower())
        out.append(replace(app, id=new_id))
        if new_id != app_id:
            changed = True
    return out, changed


def aliases_for_label(label: str) -> list[str]:
    aliases: list[str] = []
    low = label.lower()
    if low and low != label:
        aliases.append(low)
    compact = re.sub(r"\s+", "", label)
    if compact and compact not in aliases and compact != label:
        aliases.append(compact)
    stripped = re.sub(r"[!！?？.。]+$", "", label).strip()
    if stripped and stripped not in aliases and stripped != label:
        aliases.append(stripped)
    norm = normalize_match_text(label)
    if norm and norm not in aliases:
        aliases.append(norm)
    return aliases[:8]
