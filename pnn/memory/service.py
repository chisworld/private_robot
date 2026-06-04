from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from pnn.llm.config_store import load_llm_config
from pnn.memory.config_store import MemoryConfig, load_memory_config
from pnn.memory.extractor import extract_memory_from_turn
from pnn.memory.sanitize import sanitize_chat_summary, strip_expression_tags
from pnn.memory.store import MemoryStore, _chroma_available

logger = logging.getLogger(__name__)

_MOOD_LABELS = {
    "happy": "开心",
    "sad": "难过",
    "neutral": "平静",
    "angry": "生气",
    "tired": "疲惫",
}

# 退出时合并进一篇日记的最大轮数
_MAX_DIARY_TURNS = 30


class MemoryService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_user = ""
        self._last_reply = ""
        # character_id -> [(user, reply), ...] 会话内缓冲，退出时批量落盘
        self._pending_by_char: dict[str, list[tuple[str, str]]] = {}

    def _active_character_id(self) -> str:
        return (load_llm_config().active_character or "default").strip() or "default"

    def _effective_core_card(self, cfg: MemoryConfig) -> str:
        from pnn.characters.service import character_pack_service

        pack = character_pack_service.get_active_pack()
        if pack is not None and pack.memory_core_card.strip():
            return pack.memory_core_card.strip()
        return (cfg.core_card or "").strip()

    def _store(self, character_id: str | None = None) -> MemoryStore:
        cid = (character_id or self._active_character_id()).strip() or "default"
        return MemoryStore(cid)

    def _dialogue_labels(self, character_id: str | None = None) -> tuple[str, str]:
        """记忆条目中的人称：用户侧默认「主人」，助手侧用角色包 name。"""
        user_label = "主人"
        assistant_label = "助手"
        try:
            from pnn.characters.pack import load_pack

            cid = (character_id or self._active_character_id()).strip() or "default"
            pack = load_pack(cid)
            if pack is not None:
                if pack.name.strip():
                    assistant_label = pack.name.strip()
                elif pack.id.strip():
                    assistant_label = pack.id
        except Exception:
            pass
        return user_label, assistant_label

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

    def _prepare_turn_for_storage(
        self, user_message: str, assistant_reply: str
    ) -> tuple[str, str]:
        """入库用文本：去表情标签；助手回复在翻译开启时存中文译文。"""
        user = strip_expression_tags(user_message).strip()
        reply = strip_expression_tags(assistant_reply).strip()
        if not user or not reply:
            return "", ""
        try:
            from pnn.translate.service import translate_service

            if translate_service.is_enabled():
                reply = translate_service.to_display_chinese(reply)
        except Exception as exc:
            logger.warning("记忆助手译文失败，保留原文: %s", exc)
        return user, reply

    def _buffer_turn(self, user_message: str, assistant_reply: str) -> None:
        cid = self._active_character_id()
        with self._lock:
            self._pending_by_char.setdefault(cid, []).append(
                (user_message, assistant_reply)
            )
            self._last_user = user_message
            self._last_reply = assistant_reply

    def after_conversation_turn(
        self,
        user_message: str,
        assistant_reply: str,
        history: list[dict[str, str]] | None = None,
    ) -> None:
        """对话结束后：写入 chat 轮次摘要 + 可选 fact/event 提取；会话缓冲供退出写日记。"""
        cfg = load_memory_config()
        if not cfg.enabled:
            return

        user_message, assistant_reply = self._prepare_turn_for_storage(
            user_message, assistant_reply
        )
        if not user_message or not assistant_reply:
            return

        turn_key = f"{user_message[:120]}|{assistant_reply[:120]}"
        with self._lock:
            state = self._store().get_state()
            if state.get("last_processed_turn_key") == turn_key:
                return
            state["last_processed_turn_key"] = turn_key
            self._store().save_state(state)

        self._buffer_turn(user_message, assistant_reply)

        user_label, assistant_label = self._dialogue_labels()

        recent = ""
        if history:
            tail = history[-4:]
            recent = "\n".join(
                f"{user_label if m.get('role') == 'user' else assistant_label}："
                f"{strip_expression_tags(str(m.get('content', '')))}"
                for m in tail
                if strip_expression_tags(str(m.get("content", "")))
            )

        if cfg.extraction_enabled:
            parsed = extract_memory_from_turn(
                user_message,
                assistant_reply,
                recent_history=recent,
                max_tokens=cfg.extraction_max_tokens,
                user_label=user_label,
                assistant_label=assistant_label,
            )
            if parsed:
                chat_summary = sanitize_chat_summary(
                    str(parsed.get("chat_summary") or "")
                )
                if chat_summary:
                    try:
                        with self._lock:
                            self._write_chat_summary(self._store(), chat_summary)
                        logger.info("已写入对话摘要 [chat]")
                    except Exception as exc:
                        logger.warning("对话摘要写入失败: %s", exc)
                if parsed.get("save"):
                    self._apply_extracted(parsed, cfg)
        else:
            fallback = self._fallback_chat_summary(
                user_message,
                assistant_reply,
                user_label=user_label,
                assistant_label=assistant_label,
            )
            if fallback:
                try:
                    with self._lock:
                        self._write_chat_summary(self._store(), fallback)
                except Exception as exc:
                    logger.warning("对话摘要写入失败: %s", exc)

    def _fallback_chat_summary(
        self,
        user_message: str,
        assistant_reply: str,
        *,
        user_label: str,
        assistant_label: str,
    ) -> str:
        u = user_message[:60].strip()
        r = assistant_reply[:80].strip()
        return f"{user_label}{u}时，{assistant_label}回应：{r}"

    def _write_chat_summary(self, store: MemoryStore, summary: str) -> None:
        text = sanitize_chat_summary(summary)
        if not text:
            return
        store.add(text, kind="chat", importance=3.0, initial_score=0.85)

    def _format_session_diary(
        self,
        turns: list[tuple[str, str]],
        *,
        user_label: str,
        assistant_label: str,
    ) -> str:
        lines: list[str] = []
        for user, reply in turns[-_MAX_DIARY_TURNS:]:
            lines.append(
                f"{user_label}：{user[:200]}\n{assistant_label}：{reply[:200]}"
            )
        header = f"本次会话共 {len(turns)} 轮对话摘要：\n"
        return header + "\n---\n".join(lines)

    def flush_session_writes(self, character_id: str | None = None) -> int:
        """将缓冲的对话与日记一次性写入（桌宠退出 / API 关闭时调用）。"""
        cfg = load_memory_config()
        if not cfg.enabled:
            return 0

        cid = (character_id or self._active_character_id()).strip() or "default"
        with self._lock:
            turns = self._pending_by_char.pop(cid, [])
        if not turns:
            return 0

        store = self._store(cid)
        user_label, assistant_label = self._dialogue_labels(cid)
        try:
            if cfg.diary_enabled:
                today = datetime.now().strftime("%Y-%m-%d")
                state = store.get_state()
                if state.get("last_diary_date") != today:
                    store.add_diary(
                        self._format_session_diary(
                            turns,
                            user_label=user_label,
                            assistant_label=assistant_label,
                        )
                    )
                    state["last_diary_date"] = today
                    store.save_state(state)

            logger.info(
                "已写入会话日记：角色=%s 本轮 %d 轮（事实类记忆由每轮提取写入）",
                cid,
                len(turns),
            )
            return len(turns)
        except Exception as exc:
            logger.warning("批量写入记忆失败: %s", exc)
            with self._lock:
                self._pending_by_char.setdefault(cid, []).extend(turns)
            return 0

    def flush_all_session_writes(self) -> int:
        with self._lock:
            char_ids = list(self._pending_by_char.keys())
        total = 0
        for cid in char_ids:
            total += self.flush_session_writes(cid)
        return total

    def _apply_extracted(self, parsed: dict[str, Any], cfg: MemoryConfig) -> None:
        content = strip_expression_tags(str(parsed.get("content") or ""))
        if not content:
            return
        kind = str(parsed.get("kind") or "fact")
        if kind == "chat" or content.startswith("【对话记录】"):
            logger.debug("跳过全文式 chat 记忆（本轮已用 chat_summary 概括）")
            return
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
            rec = self._store().add_diary(strip_expression_tags(summary))
            return {"id": rec.id, "content": rec.content}

    def on_shutdown(self) -> None:
        """桌宠退出：批量落盘本会话对话与日记。"""
        self.flush_all_session_writes()


memory_service = MemoryService()
