from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from pnn.llm.config_store import load_llm_config
from pnn.memory.config_store import MemoryConfig, load_memory_config
from pnn.memory.extractor import extract_memory_from_turn
from pnn.memory.sanitize import (
    is_idle_proactive_memory_user_line,
    is_system_proactive_turn,
    strip_expression_tags,
)
from pnn.memory.time_label import memory_record_date
from pnn.memory.retrieval import expand_search_query, is_negative_memory
from pnn.memory.presence_recall import (
    backfill_presence_hits,
    format_presence_recall_block,
    is_past_topic_query,
    search_presence_logs,
)
from pnn.memory.store import MemoryRecord, MemoryStore, _chroma_available

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
        # character_id -> MemoryStore（避免每轮对话重复加载 JSON / 初始化 Chroma）
        self._stores: dict[str, MemoryStore] = {}
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
        with self._lock:
            store = self._stores.get(cid)
            if store is None:
                store = MemoryStore(cid)
                self._stores[cid] = store
            return store

    def _dialogue_labels(self, character_id: str | None = None) -> tuple[str, str]:
        """记忆/对话记录中的人称：里想奈侧用「哥哥」，其余默认「主人」；助手用角色包 name。"""
        cid = (character_id or self._active_character_id()).strip() or "default"
        user_label = "哥哥" if cid == "里想奈" else "主人"
        assistant_label = "助手"
        try:
            from pnn.characters.pack import load_pack

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
        test_mode = self.is_character_test_mode()
        return {
            **cfg.__dict__,
            "chroma_available": _chroma_available(),
            "character_id": self._active_character_id(),
            "test_mode": test_mode,
            "write_enabled": cfg.enabled and not test_mode,
        }

    def is_character_test_mode(self) -> bool:
        try:
            from pnn.characters.service import character_pack_service

            pack = character_pack_service.get_active_pack()
            if pack is not None and pack.test_mode:
                return True
        except Exception:
            pass
        return False

    def is_write_enabled(self) -> bool:
        cfg = load_memory_config()
        return bool(cfg.enabled) and not self.is_character_test_mode()

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

    def _maybe_maintain_store(self, store: MemoryStore) -> None:
        """每日一次：清理假遗忘 chat/event，减轻检索噪声。"""
        today = datetime.now().strftime("%Y-%m-%d")
        state = store.get_state()
        if state.get("last_memory_cleanup") == today:
            return
        removed = store.purge_negative_memories()
        state["last_memory_cleanup"] = today
        store.save_state(state)
        if removed:
            logger.info("记忆库维护：已清理 %d 条低质量条目", removed)

    def build_prompt_context(self, user_message: str) -> str:
        """检索相关记忆，拼成注入 System 的文本块。"""
        import time

        t0 = time.monotonic()
        cfg = load_memory_config()
        if not cfg.enabled:
            return ""

        with self._lock:
            store = self._store()
            self._maybe_maintain_store(store)
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

            user_label, assistant_label = self._dialogue_labels()
            recall_mode = is_past_topic_query(user_message)
            effective_top_k = min(cfg.top_k * 2, 100) if recall_mode else cfg.top_k
            hits = store.search(
                user_message,
                top_k=effective_top_k,
                assistant_name=assistant_label,
                recall_mode=recall_mode,
            )

            presence_hits = search_presence_logs(
                user_message,
                days=14,
                max_hits=8 if recall_mode else 4,
                min_score=0.1 if recall_mode else 0.14,
            )
            if presence_hits and self.is_write_enabled():
                backfill_presence_hits(
                    store,
                    presence_hits,
                    user_label=user_label,
                    assistant_label=assistant_label,
                )
                if recall_mode or not hits:
                    extra = store.search(
                        user_message,
                        top_k=min(6, effective_top_k),
                        assistant_name=assistant_label,
                        recall_mode=True,
                    )
                    seen_ids = {r.id for r in hits}
                    for rec in extra:
                        if rec.id not in seen_ids:
                            hits.append(rec)
                            seen_ids.add(rec.id)
                    hits = hits[:effective_top_k]

            if hits:
                from pnn.memory.time_label import format_memory_line

                lines = [
                    format_memory_line(
                        kind=r.kind,
                        content=r.content,
                        created_at=r.created_at,
                    )
                    for r in hits
                ]
                parts.append("【与本轮相关的长期记忆】\n" + "\n".join(lines))
                expanded = expand_search_query(user_message, assistant_name=assistant_label)
                logger.info(
                    "记忆检索 query=%r expanded=%r 命中 %d 条（角色=%s）",
                    user_message[:40],
                    expanded[:56] if expanded != user_message else "-",
                    len(hits),
                    self._active_character_id(),
                )
                for r in hits[:3]:
                    logger.info("  ↳ [%s] %s", r.kind, r.content[:72])
            else:
                logger.info(
                    "记忆检索 query=%r 无命中（角色=%s）",
                    user_message[:48],
                    self._active_character_id(),
                )

            if presence_hits:
                parts.append(format_presence_recall_block(presence_hits))
                logger.info(
                    "presence 日志补检索命中 %d 条（recall_mode=%s）",
                    len(presence_hits),
                    recall_mode,
                )

            diaries = store.list_recent_diaries(2)
            if diaries:
                dlines = [f"- {d.content[:400]}" for d in diaries]
                parts.append("【近期日记摘要】\n" + "\n".join(dlines))

            memory_rules = (
                "【记忆使用规则】以上记忆与对话存档仅供你内心参考；若与本轮问题相关，必须据此回答，"
                "不得假装不记得，严禁否认发生过；回复时自然融入角色语气，"
                "禁止对用户提及「记忆」「想起」「思い出した」「根据长期记忆」等元叙述。"
                "条目含「昨天/前天/日期」的，回复中禁止说成「今天刚发生」；"
                "用户未在本轮提起旧事时，不要主动重提无关旧伤/旧事件。"
            )
            if recall_mode or presence_hits:
                memory_rules += (
                    " 用户正在提起过去的事：必须结合上述记录如实回应，"
                    "禁止用「没有发生过」「你记错了」「在做梦吗」等否认句式。"
                )
            parts.append(memory_rules)

            elapsed_ms = int((time.monotonic() - t0) * 1000)
            if elapsed_ms >= 800:
                logger.warning(
                    "记忆检索耗时 %dms（top_k=%d）；若发消息常卡在「思考中」，可适当调低每轮检索条数",
                    elapsed_ms,
                    cfg.top_k,
                )
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

    def extract_turn_events(
        self,
        user_message: str,
        assistant_reply: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any] | None:
        """仅 DeepSeek 提取 [event]/fact，不写 dialogue。"""
        cfg = load_memory_config()
        if not cfg.enabled or not cfg.extraction_enabled:
            return None

        user_message, assistant_reply = self._prepare_turn_for_storage(
            user_message, assistant_reply
        )
        if not user_message or not assistant_reply:
            return None

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

        related = ""
        try:
            from pnn.memory.time_label import format_memory_line

            store = self._store()
            hits = store.search(
                f"{user_message}\n{assistant_reply}",
                top_k=cfg.top_k,
                assistant_name=assistant_label,
            )
            if hits:
                related = "\n".join(
                    format_memory_line(
                        kind=r.kind,
                        content=r.content,
                        created_at=r.created_at,
                    )
                    for r in hits
                )
        except Exception:
            related = ""

        now_text = datetime.now().strftime("%Y-%m-%d %H:%M")
        return extract_memory_from_turn(
            user_message,
            assistant_reply,
            recent_history=recent,
            related_memories=related,
            now_text=now_text,
            max_tokens=cfg.extraction_max_tokens,
            user_label=user_label,
            assistant_label=assistant_label,
        )

    def after_conversation_turn(
        self,
        user_message: str,
        assistant_reply: str,
        history: list[dict[str, str]] | None = None,
        *,
        pre_extracted: dict[str, Any] | None = None,
        skip_extraction: bool = False,
    ) -> None:
        """对话结束后：写入 chat 轮次摘要 + 可选 fact/event 提取；会话缓冲供退出写日记。"""
        if not self.is_write_enabled():
            if self.is_character_test_mode():
                logger.debug("skip memory write: character test mode")
            return

        cfg = load_memory_config()

        if is_system_proactive_turn(user_message):
            logger.debug("skip memory for internal proactive turn")
            return

        user_message, assistant_reply = self._prepare_turn_for_storage(
            user_message, assistant_reply
        )
        if is_idle_proactive_memory_user_line(user_message):
            logger.debug("skip memory for idle proactive turn")
            return

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

        try:
            with self._lock:
                self._write_dialogue_record(
                    self._store(),
                    user_message,
                    assistant_reply,
                    user_label=user_label,
                    assistant_label=assistant_label,
                )
        except Exception as exc:
            logger.warning("对话记录写入失败: %s", exc)

        if not cfg.extraction_enabled:
            return

        if skip_extraction:
            if pre_extracted and pre_extracted.get("save"):
                self._apply_extracted(
                    pre_extracted,
                    cfg,
                    user_message=user_message,
                    assistant_reply=assistant_reply,
                )
            return

        if pre_extracted is not None:
            if pre_extracted.get("save"):
                self._apply_extracted(
                    pre_extracted,
                    cfg,
                    user_message=user_message,
                    assistant_reply=assistant_reply,
                )
            return

        parsed = self.extract_turn_events(user_message, assistant_reply, history)
        if parsed and parsed.get("save"):
            self._apply_extracted(
                parsed,
                cfg,
                user_message=user_message,
                assistant_reply=assistant_reply,
            )

    def after_proactive_turn(
        self,
        system_context: str,
        assistant_reply: str,
        history: list[dict[str, str]] | None = None,
    ) -> None:
        """系统主动搭话：日程提醒可保留；空闲搭话不写入记忆。"""
        from pnn.memory.sanitize import (
            is_schedule_proactive_context,
            proactive_memory_user_line,
        )

        user_line = proactive_memory_user_line(system_context)
        if not is_schedule_proactive_context(system_context):
            if is_idle_proactive_memory_user_line(user_line):
                logger.debug("skip memory for idle proactive turn")
                return
        self.after_conversation_turn(
            user_line,
            assistant_reply,
            history,
            skip_extraction=True,
        )

    def after_idle_assistant_turn(
        self,
        assistant_reply: str,
        *,
        trigger: str = "时段问候",
        history: list[dict[str, str]] | None = None,
    ) -> None:
        """无用户输入的助手独白（时段问候等）：不写入记忆。"""
        logger.debug("skip memory for idle assistant turn (%s)", trigger.strip() or "时段问候")

    def _write_dialogue_record(
        self,
        store: MemoryStore,
        user_message: str,
        assistant_reply: str,
        *,
        user_label: str,
        assistant_label: str,
    ) -> None:
        """记忆库写入完整一轮对话（非一句摘要）。"""
        user = user_message.strip()
        reply = assistant_reply.strip()
        if not user or not reply:
            return
        block = f"{user_label}：{user}\n{assistant_label}：{reply}"
        if store.has_exact_content(block, kind="dialogue"):
            logger.debug("skip duplicate dialogue record")
            return
        store.add(block, kind="dialogue", importance=4.0, initial_score=0.88)
        logger.info("已写入完整对话 [dialogue]")

    def _format_session_diary(
        self,
        turns: list[tuple[str, str]],
        *,
        user_label: str,
        assistant_label: str,
    ) -> str:
        lines: list[str] = []
        for user, reply in turns[-_MAX_DIARY_TURNS:]:
            lines.append(f"{user_label}：{user.strip()}\n{assistant_label}：{reply.strip()}")
        header = f"本次会话完整对话（{len(turns)} 轮）：\n\n"
        return header + "\n\n---\n\n".join(lines)

    def flush_session_writes(self, character_id: str | None = None) -> int:
        """将缓冲的对话与日记一次性写入（桌宠退出 / API 关闭时调用）。"""
        if not self.is_write_enabled():
            cid = (character_id or self._active_character_id()).strip() or "default"
            with self._lock:
                self._pending_by_char.pop(cid, [])
            return 0

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
                "已写入会话日记：角色=%s 本轮 %d 轮完整对话（事实/事件由每轮提取写入）",
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

    def _apply_extracted(
        self,
        parsed: dict[str, Any],
        cfg: MemoryConfig,
        *,
        user_message: str = "",
        assistant_reply: str = "",
    ) -> None:
        content = strip_expression_tags(str(parsed.get("content") or ""))
        if not content:
            return
        if is_negative_memory(content):
            logger.info("跳过假遗忘 fact/event: %s", content[:64])
            return
        kind = str(parsed.get("kind") or "fact")
        if kind in ("fact", "event", "emotion"):
            from pnn.memory.recall_guard import is_recall_only_extraction

            if is_recall_only_extraction(user_message, assistant_reply, content):
                logger.info("跳过回忆式重复提取: %s", content[:64])
                return
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
            if kind == "event":
                try:
                    from pnn.pet.reminders.from_chat import (
                        try_create_reminder_from_memory_event,
                    )
                    from pnn.pet.reminders.manager import session_key_from_character

                    char_name = ""
                    try:
                        from pnn.characters.pack import load_pack

                        pack = load_pack(self._active_character_id())
                        if pack is not None and pack.name.strip():
                            char_name = pack.name.strip()
                    except Exception:
                        pass
                    sk = session_key_from_character(self._active_character_id())
                    try_create_reminder_from_memory_event(
                        sk,
                        content,
                        character_name=char_name,
                    )
                except Exception as exc:
                    logger.warning("记忆 event 同步日程失败: %s", exc)

    def list_memories(
        self,
        limit: int = 50,
        *,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        from pnn.memory.kinds import kind_label
        from pnn.memory.store import _keyword_similarity
        from pnn.memory.time_label import memory_age_label

        with self._lock:
            store = self._store()
            kind_filter = (kind or "").strip().lower() or None
            items = store.list_all(0, kind=kind_filter)
            filtered: list[dict[str, Any]] = []
            query = (q or "").strip().lower()
            start_day = (date_from or "").strip()[:10] or None
            end_day = (date_to or "").strip()[:10] or None
            for r in items:
                record_day = memory_record_date(r.created_at, r.updated_at)
                if start_day and record_day and record_day < start_day:
                    continue
                if end_day and record_day and record_day > end_day:
                    continue
                body = (r.content or "").strip()
                if query:
                    blob = body.lower()
                    if query not in blob and _keyword_similarity(query, blob) < 0.14:
                        continue
                filtered.append(self._memory_item_dict(r))
                if len(filtered) >= limit:
                    break
            return filtered

    def list_dialogue_history(self, limit: int = 500, *, days: int = 60) -> list[dict[str, Any]]:
        from pnn.memory.dialogue_history import load_dialogue_history

        with self._lock:
            user_label, assistant_label = self._dialogue_labels()
            return load_dialogue_history(
                store=self._store(),
                user_label=user_label,
                assistant_label=assistant_label,
                days=days,
                limit=limit,
            )

    def memory_stats(self) -> dict[str, Any]:
        from pnn.memory.kinds import ALL_KINDS, format_kind_stats, kind_meta

        with self._lock:
            store = self._store()
            counts = store.count_by_kind()
            total = sum(counts.values())
            kinds = [
                {
                    "kind": k,
                    "label": kind_meta(k).label,
                    "count": int(counts.get(k, 0)),
                    "color": kind_meta(k).color,
                    "description": kind_meta(k).description,
                }
                for k in ALL_KINDS
                if counts.get(k, 0)
            ]
            kinds.sort(key=lambda x: kind_meta(str(x["kind"])).sort)
            return {
                "total": total,
                "counts": counts,
                "summary": format_kind_stats(counts),
                "kinds": kinds,
                "chroma_available": _chroma_available(),
                "character_id": self._active_character_id(),
                "test_mode": self.is_character_test_mode(),
                "write_enabled": self.is_write_enabled(),
            }

    @staticmethod
    def _memory_item_dict(r: MemoryRecord) -> dict[str, Any]:
        from pnn.memory.kinds import kind_label
        from pnn.memory.time_label import memory_age_label

        created = str(r.created_at or "")
        updated = str(r.updated_at or "")
        record_day = memory_record_date(created, updated)
        return {
            "id": r.id,
            "content": r.content,
            "kind": r.kind,
            "kind_label": kind_label(r.kind),
            "importance": r.importance,
            "score": r.score,
            "access_count": r.access_count,
            "updated_at": updated,
            "created_at": created,
            "record_date": record_day,
            "age_label": memory_age_label(created),
        }

    def delete_memory(self, memory_id: str) -> None:
        with self._lock:
            self._store().delete(memory_id)

    def write_diary_now(self, summary: str) -> dict[str, str]:
        if not self.is_write_enabled():
            raise ValueError("当前为测试模式或记忆已关闭，无法写入日记")
        with self._lock:
            rec = self._store().add_diary(strip_expression_tags(summary))
            return {"id": rec.id, "content": rec.content}

    def on_shutdown(self) -> None:
        """桌宠退出：批量落盘本会话对话与日记。"""
        self.flush_all_session_writes()


memory_service = MemoryService()
