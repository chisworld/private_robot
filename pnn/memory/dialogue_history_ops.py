"""对话历史删除：记忆库 dialogue、会话日志、关联 fact/event。"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from pnn.memory.dialogue_history import _MERGE_SEP, _parse_dialogue_block

logger = logging.getLogger(__name__)

_LINKED_KINDS = frozenset({"fact", "event", "emotion"})


def _parse_at(at: str) -> datetime | None:
    raw = (at or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _snippets(user: str, assistant: str) -> list[str]:
    out: list[str] = []
    for piece in (user, assistant):
        t = re.sub(r"\s+", " ", (piece or "").strip())
        if len(t) >= 6:
            out.append(t[:80])
        if len(t) >= 12:
            out.append(t[:40])
    return out


def delete_linked_extractions(
    store,
    *,
    user: str,
    assistant: str,
    at: str,
) -> int:
    """删除与该轮对话时间/内容相近的 fact/event/emotion。"""
    dt = _parse_at(at)
    snippets = _snippets(user, assistant)
    removed = 0
    for rec in list(store.list_all(0)):
        if rec.kind not in _LINKED_KINDS:
            continue
        body = (rec.content or "").strip()
        if not body:
            continue
        text_hit = any(sn in body for sn in snippets)
        time_hit = False
        if dt is not None and (rec.created_at or "").strip():
            try:
                rdt = datetime.fromisoformat(rec.created_at.replace("Z", "+00:00"))
                time_hit = dt - timedelta(minutes=3) <= rdt <= dt + timedelta(minutes=20)
            except ValueError:
                time_hit = False
        if text_hit or time_hit:
            store.delete(rec.id)
            removed += 1
    return removed


def remove_turn_from_dialogue_record(
    store,
    memory_id: str,
    *,
    user: str,
    assistant: str,
    user_label: str,
    assistant_label: str,
    turn_index: int | None = None,
) -> bool:
    rec = store._records.get(memory_id)
    if rec is None or rec.kind != "dialogue":
        return False
    body = (rec.content or "").strip()
    if not body:
        store.delete(memory_id)
        return True
    blocks = _MERGE_SEP.split(body) if _MERGE_SEP.search(body) else [body]
    pairs = []
    for block in blocks:
        for u, a in _parse_dialogue_block(
            block, user_label=user_label, assistant_label=assistant_label
        ):
            pairs.append((u, a))
    if not pairs:
        store.delete(memory_id)
        return True
    target_u = (user or "").strip()
    target_a = (assistant or "").strip()
    kept: list[tuple[str, str]] = []
    for i, (u, a) in enumerate(pairs):
        if turn_index is not None and i == turn_index:
            continue
        if turn_index is None and u == target_u and a == target_a:
            continue
        kept.append((u, a))
    if len(kept) == len(pairs):
        return False
    if not kept:
        store.delete(memory_id)
        return True
    new_blocks = [
        f"{user_label}：{u}\n{assistant_label}：{a}" for u, a in kept if u or a
    ]
    new_body = "\n\n---\n\n".join(new_blocks)
    return store.replace_content(memory_id, new_body)


def remove_daily_log_turn(
    log_path: str,
    log_index: int | None,
    *,
    at: str,
    user: str,
    assistant: str,
) -> bool:
    path = Path(log_path)
    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(raw, list):
        return False
    target_u = (user or "").strip()
    target_a = (assistant or "").strip()
    target_at = (at or "").strip()
    new_list: list = []
    removed = False
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            new_list.append(item)
            continue
        if log_index is not None and idx == log_index:
            removed = True
            continue
        u = str(item.get("user") or "").strip()
        a = str(item.get("assistant") or "").strip()
        item_at = str(item.get("at") or "").strip()
        if (
            not removed
            and u == target_u
            and a == target_a
            and (not target_at or item_at == target_at or item_at[:16] == target_at[:16])
        ):
            removed = True
            continue
        new_list.append(item)
    if not removed:
        return False
    path.write_text(json.dumps(new_list, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
