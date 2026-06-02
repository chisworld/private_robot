from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from pnn.llm.config_store import load_llm_config
from pnn.memory.config_store import MemoryConfig, load_memory_config
from pnn.memory.extractor import extract_memory_from_turn
from pnn.memory.store import MemoryStore, _chroma_available

logger = logging.getLogger(__name__)

_MOOD_LABELS = {
    "happy": "开心",
    "sad": "难过",
    "neutral": "平静",
    "angry": "生气",
    "tired": "疲惫",
}


class MemoryService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_user = ""
        self._last_reply = ""

    def _active_character_id(self) -> str:
        return (load_llm_config().active_character or "default").strip() or "default"

    def _effective_core_card(self, cfg: MemoryConfig) -> str:
        from pnn.characters.service import character_pack_service

        pack = character_pack_service.get_active_pack()
        if pack is not None and pack.memory_core_card.strip():
            return pack.memory_core_card.strip()
        return (cfg.core_card or "").strip()

    def _store(self) -> MemoryStore:
        return MemoryStore(self._active_character_id())

    def get_config(self) -> dict[str, Any]:
        cfg = load_memory_config()
        return {
            **cfg.__dict__,
            "chroma_available": _chroma_available(),
            "character_id": self._active_character_id(),
        }

    def update_config(self, **kwargs: Any) -> dict[str, Any]:
        from pnn.memory.config_store import save_memory_config

        cfg = load_memory_config()
        for key, value in kwargs.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        save_memory_config(cfg)
        if "core_card" in kwargs:
            self._sync_core_card_to_pack(str(kwargs.get("core_card") or ""))
        return self.get_config()

    def _sync_core_card_to_pack(self, core: str) -> None:
        from pnn.characters.service import character_pack_service

        pack = character_pack_service.get_active_pack()
        if pack is None:
            return
        pack.memory_core_card = core.strip()
        character_pack_service.save_pack_data(pack)

    def build_prompt_context(self, user_message: str) -> str:
        """检索相关记忆，拼成注入 System 的文本块。"""
        cfg = load_memory_config()
        if not cfg.enabled:
            return ""

        with self._lock:
            store = self._store()
            store.apply_decay(cfg.decay_per_day, cfg.min_score)
            state = store.get_state()
            affection = int(state.get("affection", cfg.affection_initial))
            mood = str(state.get("mood", "neutral"))
            mood_zh = _MOOD_LABELS.get(mood, mood)

            parts: list[str] = []
            core = self._effective_core_card(cfg)
            if core:
                parts.append(f"【核心设定·永不覆盖】\n{core}")

            parts.append(f"【当前状态】好感度 {affection}/100，心情：{mood_zh}")

            hits = store.search(user_message, top_k=cfg.top_k)
            if hits:
                lines = [f"- {r.content}" for r in hits]
                parts.append("【与本轮相关的长期记忆】\n" + "\n".join(lines))

            diaries = store.list_recent_diaries(2)
            if diaries:
                dlines = [f"- {d.content[:400]}" for d in diaries]
                parts.append("【近期日记摘要】\n" + "\n".join(dlines))

            return "\n\n".join(parts)

    def after_conversation_turn(
        self,
        user_message: str,
        assistant_reply: str,
        history: list[dict[str, str]] | None = None,
    ) -> None:
        """对话结束后后台：提取记忆、更新好感/心情。"""
        cfg = load_memory_config()
        if not cfg.enabled:
            return

        user_message = (user_message or "").strip()
        assistant_reply = (assistant_reply or "").strip()
        if not user_message or not assistant_reply:
            return

        turn_key = f"{user_message[:120]}|{assistant_reply[:120]}"
        with self._lock:
            store = self._store()
            state = store.get_state()
            if state.get("last_processed_turn_key") == turn_key:
                return
            state["last_processed_turn_key"] = turn_key
            store.save_state(state)
            self._last_user = user_message
            self._last_reply = assistant_reply

        self._record_chat_turn(user_message, assistant_reply)

        recent = ""
        if history:
            tail = history[-4:]
            recent = "\n".join(
                f"{'主人' if m.get('role') == 'user' else '桌宠'}：{m.get('content', '')}"
                for m in tail
                if m.get("content")
            )

        if cfg.extraction_enabled:
            parsed = extract_memory_from_turn(
                user_message,
                assistant_reply,
                recent_history=recent,
                max_tokens=cfg.extraction_max_tokens,
            )
            if parsed and parsed.get("save"):
                self._apply_extracted(parsed, cfg)

        self._maybe_write_diary(cfg, user_message, assistant_reply)

    def _record_chat_turn(self, user_message: str, assistant_reply: str) -> None:
        """每轮对话写入记忆库（可在设置页「记忆」列表中看到）。"""
        snippet = (
            f"【对话记录】\n主人：{user_message[:400]}\n"
            f"树里亚：{assistant_reply[:400]}"
        )
        try:
            with self._lock:
                self._store().add(
                    snippet,
                    kind="chat",
                    importance=4.0,
                    initial_score=0.9,
                )
            logger.info("已写入对话记录到记忆库")
        except Exception as exc:
            logger.warning("对话记录写入失败: %s", exc)

    def _apply_extracted(self, parsed: dict[str, Any], cfg: MemoryConfig) -> None:
        content = str(parsed.get("content") or "").strip()
        if not content:
            return
        kind = str(parsed.get("kind") or "fact")
        try:
            importance = float(parsed.get("importance", 5))
        except (TypeError, ValueError):
            importance = 5.0

        with self._lock:
            store = self._store()
            store.add(content, kind=kind, importance=importance)
            state = store.get_state()
            try:
                aff = int(state.get("affection", cfg.affection_initial))
                aff += int(parsed.get("affection_delta") or 0)
                aff = max(cfg.affection_min, min(cfg.affection_max, aff))
                state["affection"] = aff
            except (TypeError, ValueError):
                pass
            md = parsed.get("mood_delta")
            if isinstance(md, int) and md != 0:
                cur = str(state.get("mood", "neutral"))
                if md > 2:
                    state["mood"] = "happy"
                elif md < -2:
                    state["mood"] = "sad"
                else:
                    state["mood"] = cur
            store.save_state(state)
            logger.info("已写入记忆 [%s]: %s", kind, content[:80])

    def _maybe_write_diary(
        self, cfg: MemoryConfig, user_message: str, assistant_reply: str
    ) -> None:
        if not cfg.diary_enabled:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            store = self._store()
            state = store.get_state()
            if state.get("last_diary_date") == today:
                return
            body = (
                f"主人说：{user_message[:200]}\n"
                f"桌宠答：{assistant_reply[:200]}"
            )
            store.add_diary(body)
            state["last_diary_date"] = today
            store.save_state(state)

    def list_memories(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            store = self._store()
            items = store.list_all(limit)
            return [
                {
                    "id": r.id,
                    "content": r.content,
                    "kind": r.kind,
                    "importance": r.importance,
                    "score": r.score,
                    "updated_at": r.updated_at,
                }
                for r in items
            ]

    def delete_memory(self, memory_id: str) -> None:
        with self._lock:
            self._store().delete(memory_id)

    def write_diary_now(self, summary: str) -> dict[str, str]:
        with self._lock:
            rec = self._store().add_diary(summary)
            return {"id": rec.id, "content": rec.content}

    def on_shutdown(self) -> None:
        """桌宠退出时补一篇日记（若今日尚未写过）。"""
        cfg = load_memory_config()
        if not cfg.enabled or not cfg.diary_enabled:
            return
        with self._lock:
            user = self._last_user
            reply = self._last_reply
        if not user or not reply:
            return
        summary = f"今日最后一轮：主人说「{user[:120]}」，桌宠答「{reply[:120]}」。"
        self._maybe_write_diary(cfg, user, reply)
        with self._lock:
            store = self._store()
            state = store.get_state()
            if state.get("last_diary_date") != datetime.now().strftime("%Y-%m-%d"):
                store.add_diary(summary)
                state["last_diary_date"] = datetime.now().strftime("%Y-%m-%d")
                store.save_state(state)


memory_service = MemoryService()
