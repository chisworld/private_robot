from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pnn.core.paths import DATA_DIR

logger = logging.getLogger(__name__)

MEMORY_DATA_DIR = DATA_DIR / "memory"

_CHROMA_OK: bool | None = None


def _chroma_available() -> bool:
    global _CHROMA_OK
    if _CHROMA_OK is not None:
        return _CHROMA_OK
    try:
        import chromadb  # noqa: F401

        _CHROMA_OK = True
    except ImportError:
        _CHROMA_OK = False
        logger.info("未安装 chromadb，记忆检索使用本地关键词回退（pip install chromadb 可启用向量 RAG）")
    return _CHROMA_OK


@dataclass
class MemoryRecord:
    id: str
    content: str
    kind: str = "fact"
    importance: float = 5.0
    score: float = 1.0
    created_at: str = ""
    updated_at: str = ""
    access_count: int = 0

    def to_meta(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "importance": float(self.importance),
            "score": float(self.score),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": int(self.access_count),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_memory_id(existing: set[str] | None = None) -> str:
    """可读时间 ID（本地时区），替代 uuid 短哈希。"""
    taken = existing or set()
    now = datetime.now().astimezone()
    base = now.strftime("%Y-%m-%dT%H:%M:%S")
    candidate = f"{base}.{now.microsecond:06d}"
    if candidate not in taken:
        return candidate
    for i in range(1, 1000):
        alt = f"{candidate}_{i}"
        if alt not in taken:
            return alt
    return uuid.uuid4().hex[:12]


def _char_dir(character_id: str) -> Path:
    safe = re.sub(r'[<>:"/\\|?*]', "_", (character_id or "default").strip()) or "default"
    return MEMORY_DATA_DIR / safe


class MemoryStore:
    """按角色隔离；优先 Chroma 向量库，否则 JSON + 关键词相似度。"""

    def __init__(self, character_id: str) -> None:
        self.character_id = (character_id or "default").strip() or "default"
        self._dir = _char_dir(self.character_id)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "memories.json"
        self._state_path = self._dir / "state.json"
        self._records: dict[str, MemoryRecord] = {}
        self._collection = None
        self._load_index()
        self._init_chroma()

    def _load_index(self) -> None:
        if not self._index_path.is_file():
            return
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            for item in raw.get("items", []):
                rec = MemoryRecord(
                    id=str(item["id"]),
                    content=str(item["content"]),
                    kind=str(item.get("kind", "fact")),
                    importance=float(item.get("importance", 5)),
                    score=float(item.get("score", 1.0)),
                    created_at=str(item.get("created_at", "")),
                    updated_at=str(item.get("updated_at", "")),
                    access_count=int(item.get("access_count", 0)),
                )
                self._records[rec.id] = rec
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("记忆索引损坏，将重建: %s", exc)
            self._records.clear()

    def _save_index(self) -> None:
        payload = {
            "character_id": self.character_id,
            "items": [asdict(r) for r in self._records.values()],
        }
        self._index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _init_chroma(self) -> None:
        if not _chroma_available():
            return
        try:
            import chromadb

            client = chromadb.PersistentClient(path=str(self._dir / "chroma"))
            self._collection = client.get_or_create_collection(
                name="memories",
                metadata={"hnsw:space": "cosine"},
            )
            self._sync_chroma()
        except Exception as exc:
            logger.warning("Chroma 初始化失败，使用关键词回退: %s", exc)
            self._collection = None

    def _sync_chroma(self) -> None:
        if self._collection is None:
            return
        try:
            existing = set(self._collection.get(include=[])["ids"])
        except Exception:
            existing = set()
        for rec in self._records.values():
            if rec.id in existing:
                continue
            self._collection.add(
                ids=[rec.id],
                documents=[rec.content],
                metadatas=[rec.to_meta()],
            )

    def get_state(self) -> dict[str, Any]:
        if self._state_path.is_file():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {"affection": 80, "mood": "neutral", "last_decay": _now_iso()}

    def save_state(self, state: dict[str, Any]) -> None:
        self._state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def apply_decay(self, decay_per_day: float, min_score: float) -> int:
        if decay_per_day <= 0:
            return 0
        state = self.get_state()
        last = state.get("last_decay") or _now_iso()
        try:
            t0 = datetime.fromisoformat(last.replace("Z", "+00:00"))
            t1 = datetime.now(timezone.utc)
            days = max(0.0, (t1 - t0).total_seconds() / 86400.0)
        except ValueError:
            days = 1.0
        if days < 0.01:
            return 0
        factor = max(0.0, 1.0 - decay_per_day * days)
        removed = 0
        for rid in list(self._records.keys()):
            rec = self._records[rid]
            rec.score *= factor
            if rec.score < min_score:
                self.delete(rid)
                removed += 1
            else:
                rec.updated_at = _now_iso()
        state["last_decay"] = _now_iso()
        self.save_state(state)
        self._save_index()
        return removed

    def add(
        self,
        content: str,
        *,
        kind: str = "fact",
        importance: float = 5.0,
        initial_score: float | None = None,
    ) -> MemoryRecord:
        text = content.strip()
        if not text:
            raise ValueError("记忆内容不能为空")
        if kind in ("fact", "event", "chat") and is_negative_memory(text):
            raise ValueError("低质量/假遗忘记忆不应入库")
        dup_threshold = 0.52 if kind == "event" else 0.72
        dup = self._find_similar(text, threshold=dup_threshold)
        if dup is not None:
            merged_text = text
            try:
                from pnn.memory.config_store import load_memory_config
                from pnn.memory.merger import merge_memory_with_llm

                if load_memory_config().merge_similar_with_llm:
                    llm_merged = merge_memory_with_llm(dup.content, text)
                    if llm_merged:
                        merged_text = llm_merged
            except Exception:
                pass
            dup.content = merged_text
            dup.importance = max(dup.importance, importance)
            dup.score = min(1.0, dup.score + 0.2)
            dup.updated_at = _now_iso()
            dup.access_count += 1
            self._upsert_chroma(dup)
            self._save_index()
            return dup

        score = 1.0 if initial_score is None else min(1.0, max(0.1, initial_score))
        rec = MemoryRecord(
            id=_new_memory_id(set(self._records.keys())),
            content=text,
            kind=kind,
            importance=importance,
            score=score,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        self._records[rec.id] = rec
        self._upsert_chroma(rec)
        self._save_index()
        return rec

    def _find_similar(self, content: str, threshold: float = 0.72) -> MemoryRecord | None:
        q = content.lower()
        best: MemoryRecord | None = None
        best_score = threshold
        for rec in self._records.values():
            r = _keyword_similarity(q, rec.content.lower())
            if r >= best_score:
                best_score = r
                best = rec
        return best

    def _upsert_chroma(self, rec: MemoryRecord) -> None:
        if self._collection is None:
            return
        try:
            self._collection.upsert(
                ids=[rec.id],
                documents=[rec.content],
                metadatas=[rec.to_meta()],
            )
        except Exception as exc:
            logger.debug("Chroma upsert: %s", exc)

    def delete(self, memory_id: str) -> None:
        self._records.pop(memory_id, None)
        if self._collection is not None:
            try:
                self._collection.delete(ids=[memory_id])
            except Exception:
                pass
        self._save_index()

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        assistant_name: str = "",
    ) -> list[MemoryRecord]:
        q = query.strip()
        if not q or not self._records:
            return []

        if not (assistant_name or "").strip():
            assistant_name = active_assistant_label()

        expanded = expand_search_query(q, assistant_name=assistant_name)
        queries = [q] if expanded == q else [q, expanded]

        chroma_boost: dict[str, float] = {}
        if self._collection is not None:
            try:
                res = self._collection.query(
                    query_texts=[expanded or q],
                    n_results=min(max(top_k * 4, top_k), len(self._records)),
                    include=["distances"],
                )
                ids = (res.get("ids") or [[]])[0]
                dists = (res.get("distances") or [[]])[0]
                for mid, dist in zip(ids, dists):
                    try:
                        d = float(dist)
                    except (TypeError, ValueError):
                        d = 1.0
                    chroma_boost[str(mid)] = max(0.0, 0.15 - d * 0.1)
            except Exception as exc:
                logger.debug("Chroma query 失败: %s", exc)

        def _best_relevance(rec: MemoryRecord) -> float:
            return max(
                _relevance_score(sq, rec, assistant_name=assistant_name) for sq in queries
            )

        ranked = sorted(
            self._records.values(),
            key=lambda r: _best_relevance(r) + chroma_boost.get(r.id, 0.0),
            reverse=True,
        )
        out: list[MemoryRecord] = []
        for rec in ranked:
            if is_negative_memory(rec.content) and rec.kind != "fact":
                continue
            score = _best_relevance(rec) + chroma_boost.get(rec.id, 0.0)
            if score < 0.06 and out:
                break
            if score < 0.02:
                continue
            out.append(rec)
            if len(out) >= top_k * 2:
                break

        out = dedupe_hits(out)[:top_k]
        if not out and ranked:
            out = dedupe_hits([r for r in ranked if not is_negative_memory(r.content)])[:top_k]

        for rec in out:
            rec.access_count += 1
            rec.score = min(1.0, rec.score + 0.05)
            rec.updated_at = _now_iso()
        self._save_index()
        return out

    def purge_negative_memories(self) -> int:
        """删除假遗忘类 chat/event 条目（保留 fact 供人工核对）。"""
        removed = 0
        for rid in list(self._records.keys()):
            rec = self._records[rid]
            if rec.kind in ("chat", "event") and is_negative_memory(rec.content):
                self.delete(rid)
                removed += 1
        if removed:
            logger.info("已清理 %d 条低质量记忆（角色=%s）", removed, self.character_id)
        return removed

    def add_diary(self, body: str) -> MemoryRecord:
        day = datetime.now().strftime("%Y-%m-%d")
        title = f"【{day} 日记】"
        return self.add(f"{title}\n{body.strip()}", kind="diary", importance=6.0)

    def list_recent_diaries(self, limit: int = 3) -> list[MemoryRecord]:
        diaries = [r for r in self._records.values() if r.kind == "diary"]
        diaries.sort(key=lambda r: r.updated_at, reverse=True)
        return diaries[:limit]

    def list_all(self, limit: int = 50) -> list[MemoryRecord]:
        items = sorted(self._records.values(), key=lambda r: r.updated_at, reverse=True)
        return items[:limit]


def _bigrams(text: str) -> set[str]:
    t = (text or "").strip()
    if len(t) < 2:
        return {t} if t else set()
    return {t[i : i + 2] for i in range(len(t) - 1)}


from pnn.memory.retrieval import (
    active_assistant_label,
    dedupe_hits,
    expand_search_query,
    is_negative_memory,
)


def _keyword_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.9
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    char_j = len(sa & sb) / len(sa | sb)
    ba, bb = _bigrams(a), _bigrams(b)
    if ba and bb:
        bi_j = len(ba & bb) / len(ba | bb)
        return max(char_j, bi_j * 1.15)
    return char_j


def _relevance_score(
    query: str, rec: MemoryRecord, *, assistant_name: str = ""
) -> float:
    """中文短问句 + 混合排序：字符/二元组重叠 + 关键词加分 - 假遗忘惩罚。"""
    q = (query or "").strip().lower()
    c = (rec.content or "").strip().lower()
    if not q or not c:
        return 0.0
    base = _keyword_similarity(q, c)
    term_bonus = 0.0
    name = (assistant_name or "").strip()
    for token in ("妹妹", "姐姐", "弟弟", "哥哥", "家人", "名字"):
        if token in q and token in c:
            term_bonus += 0.28
    if "妹妹" in q:
        if name and (f"{name}的妹妹" in c or (name in c and "妹妹" in c)):
            term_bonus += 0.24
        elif "有了妹妹" in c or "有了个妹妹" in c or "妹妹叫" in c:
            term_bonus += 0.18
        if "主人的妹妹" in c and (not name or f"{name}的妹妹" not in c):
            term_bonus -= 0.22
    for length in (4, 3, 2):
        for i in range(max(0, len(q) - length + 1)):
            frag = q[i : i + length]
            if len(frag) >= 2 and frag in c:
                term_bonus = max(term_bonus, 0.06 * length)
    kind_bonus = (
        0.16
        if rec.kind == "fact"
        else (0.05 if rec.kind == "event" else -0.1 if rec.kind == "chat" else -0.06)
    )
    neg = 0.65 if is_negative_memory(c) else 0.0
    weight = max(0.1, rec.score) * (rec.importance / 10.0)
    return max(0.0, (base + term_bonus + kind_bonus - neg) * weight)
