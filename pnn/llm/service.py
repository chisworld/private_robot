from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from dataclasses import asdict
from typing import Any

from pnn.llm.character_store import load_character
from pnn.llm.client import DeepSeekClient
from pnn.llm.config_store import LlmConfig, load_llm_config, mask_api_key, save_llm_config

logger = logging.getLogger(__name__)

ChatMessage = dict[str, str]


class LlmService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config = load_llm_config()
        self._last_error: str | None = None

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            self._config = load_llm_config()
            cfg = asdict(self._config)
            cfg.pop("api_key", None)
            cfg["api_key"] = ""
            cfg["api_key_masked"] = mask_api_key(self._config.api_key)
            cfg["configured"] = bool(self._config.api_key.strip())
            cfg["last_error"] = self._last_error
            cfg["characters"] = self.list_characters()
            try:
                from pnn.llm.vision_client import DASHSCOPE_VL_MODELS, vision_configured

                cfg["vision_configured"] = vision_configured()
                cfg["vision_model_options"] = [m for m, _ in DASHSCOPE_VL_MODELS]
            except Exception:
                cfg["vision_configured"] = False
                cfg["vision_model_options"] = []
            return cfg

    def update_config(self, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            config = load_llm_config()
            for key, value in kwargs.items():
                if not hasattr(config, key):
                    continue
                setattr(config, key, value)
            keep_key = bool(str(kwargs.get("api_key") or "").strip())
            save_llm_config(config, keep_api_key=keep_key)
            self._config = load_llm_config()
            self._last_error = None
            logger.info(
                "LLM 配置已更新（system_prompt 长度=%s）",
                len((config.system_prompt or "").strip()),
            )
            cfg = asdict(config)
            cfg.pop("api_key", None)
            cfg["api_key"] = ""
            cfg["api_key_masked"] = mask_api_key(config.api_key)
            cfg["configured"] = bool(config.api_key.strip())
            cfg["last_error"] = self._last_error
            cfg["characters"] = self.list_characters()
            return cfg

    def list_characters(self) -> list[dict[str, str]]:
        from pnn.llm.character_store import list_characters

        return list_characters()

    def get_character(self, char_id: str) -> dict[str, Any]:
        from pnn.llm.character_store import load_character

        ch = load_character(char_id)
        if ch is None:
            raise ValueError(f"角色不存在: {char_id}")
        return {
            "id": ch.id,
            "name": ch.name,
            "character_prompt": ch.character_prompt,
        }

    def save_character(
        self,
        char_id: str,
        *,
        name: str | None = None,
        character_prompt: str | None = None,
    ) -> dict[str, Any]:
        from pnn.llm.character_store import CharacterConfig, load_character, save_character

        cid = char_id.strip()
        existing = load_character(cid)
        if existing is None:
            existing = CharacterConfig(id=cid, name=cid, character_prompt="")
        if name is not None:
            existing.name = name
        if character_prompt is not None:
            existing.character_prompt = character_prompt
        saved = save_character(existing)
        return {
            "id": saved.id,
            "name": saved.name,
            "character_prompt": saved.character_prompt,
        }

    def _client(self) -> DeepSeekClient:
        cfg = self._config
        return DeepSeekClient(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model=cfg.model,
        )

    def _build_system_messages(self) -> list[ChatMessage]:
        """规则来自 llm.json；角色设定来自当前激活角色包。"""
        out: list[ChatMessage] = []

        char_id = (self._config.active_character or "").strip()
        # 语言规则放在最前面，避免被长角色设定淹没
        lang_rule = self._reply_language_rule(char_id)
        if lang_rule:
            out.append({"role": "system", "content": lang_rule})

        rules = (self._config.system_prompt or "").strip()
        if rules:
            out.append({"role": "system", "content": f"【输出与对话规则】\n{rules}"})

        if char_id:
            try:
                ch = load_character(char_id)
            except (ValueError, OSError) as exc:
                logger.warning("加载角色 %s 失败: %s", char_id, exc)
                ch = None
            if ch and ch.character_prompt.strip():
                label = ch.name or ch.id
                out.append(
                    {
                        "role": "system",
                        "content": f"【角色设定：{label}】\n{ch.character_prompt.strip()}",
                    }
                )
        return out

    def _reply_language_rule(self, char_id: str) -> str:
        try:
            from pnn.characters.pack import load_pack
            from pnn.characters.reply_lang import is_chinese, is_japanese, normalize_reply_language

            pack = load_pack(char_id) if char_id else None
        except Exception:
            pack = None
        lang = normalize_reply_language(pack.reply_language if pack else "ja")
        if is_japanese(lang):
            return (
                "【最重要规则 - 回复语言】你只能用日语（日本語）回复。"
                "即使用户用中文提问，你的全部回复也必须是日语。"
                "绝对禁止使用中文（简体或繁体）、英文或其他语言。"
                "这是硬性要求，违反此规则等同于任务失败。"
            )
        if is_chinese(lang):
            return (
                "【最重要规则 - 回复语言】你只能用简体中文回复。"
                "即使用户用其他语言提问，你的全部回复也必须是简体中文。"
            )
        return ""

    def _memory_context(self, user_message: str) -> str:
        try:
            from pnn.memory.service import memory_service

            return memory_service.build_prompt_context(user_message)
        except Exception as exc:
            logger.warning("记忆上下文加载失败: %s", exc)
            return ""

    def _merge_extra_system(
        self, user_message: str, extra_system: str | None
    ) -> str | None:
        parts: list[str] = []
        mem = self._memory_context(user_message)
        if mem:
            parts.append(mem)
        extra = (extra_system or "").strip()
        if extra:
            parts.append(extra)
        if not parts:
            return None
        return "\n\n".join(parts)

    def _prepare_user_message(
        self,
        text: str,
        *,
        image_base64: str | None = None,
        image_mime: str | None = None,
        image_analysis: str | None = None,
    ) -> str:
        body = (text or "").strip()
        img = (image_base64 or "").strip()
        if not img:
            if not body:
                raise ValueError("消息不能为空")
            return body

        from pnn.llm.vision_client import describe_image, vision_configured

        if not vision_configured() and not (image_analysis or "").strip():
            raise ValueError(
                "发送截图需要配置视觉模型（DeepSeek 对话 API 不支持图片）。"
                "请在 .env 设置 DASHSCOPE_API_KEY 与 DASHSCOPE_VL_MODEL（如 qwen-vl-max），"
                "或在设置 → LLM 填写「视觉模型」。"
            )

        desc = describe_image(
            img,
            image_mime or "image/png",
            user_hint=body,
            cached_analysis=image_analysis or "",
        )
        site_hint = body or "（用户未说明网站，请先询问要搜索哪个网站）"
        from pnn.agent.screenshot_download import SCREENSHOT_DOWNLOAD_TASK_BODY
        from pnn.characters.reply_lang import active_reply_language, screenshot_task_reply_note

        reply_note = screenshot_task_reply_note(active_reply_language())
        parts = [
            site_hint,
            "",
            f"【用户附带的截图分析】\n{desc}",
            "",
            SCREENSHOT_DOWNLOAD_TASK_BODY,
        ]
        if reply_note:
            parts.extend(["", reply_note])
        return "\n\n".join(parts)

    def _build_messages(
        self,
        user_message: str,
        history: list[ChatMessage] | None,
        *,
        extra_system: str | None = None,
    ) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        messages.extend(self._build_system_messages())
        merged = self._merge_extra_system(user_message, extra_system)
        if merged:
            messages.append({"role": "system", "content": merged})

        hist = list(history or [])
        cap = max(2, int(self._config.max_history_messages or 20))
        if len(hist) > cap:
            hist = hist[-cap:]

        for item in hist:
            role = (item.get("role") or "").strip()
            content = (item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message.strip()})
        return messages

    def reload_from_disk(self) -> None:
        """每次对话前从 llm.json 重新加载，确保刚保存的提示词立即生效。"""
        with self._lock:
            self._config = load_llm_config()

    def _ensure_configured(self) -> None:
        self.reload_from_disk()
        if not self._config.api_key.strip():
            raise ValueError(
                "未配置 DeepSeek API Key。请在聊天页设置中填写，"
                "或在项目根 .env 中设置 DEEPSEEK_API_KEY（见 .env.example）"
            )

    def _should_use_agent(self) -> bool:
        try:
            from pnn.mcp.service import mcp_service

            if not mcp_service.chat_enabled():
                return False
            tools = mcp_service.tools_for_openai(connect=False)
            if tools:
                return True
            # 尚未连接时尝试拉取工具列表（会触发 connect）
            return bool(mcp_service.tools_for_openai(connect=True))
        except Exception as exc:
            logger.debug("MCP Agent 不可用: %s", exc)
            return False

    def agent_enabled(self) -> bool:
        with self._lock:
            self.reload_from_disk()
            return self._should_use_agent()

    def iter_agent_events(
        self,
        user_message: str,
        history: list[ChatMessage] | None = None,
        *,
        extra_system: str | None = None,
        image_base64: str | None = None,
        image_mime: str | None = None,
        image_analysis: str | None = None,
    ) -> Iterator[tuple[str, str]]:
        """Agent 模式：yield ('status', msg) 或 ('delta', chunk)。"""
        from pnn.agent.orchestrator import AgentOrchestrator

        with self._lock:
            self._ensure_configured()
            if image_base64 and not (image_analysis or "").strip():
                yield ("status", "正在分析截图…")
            text = self._prepare_user_message(
                user_message,
                image_base64=image_base64,
                image_mime=image_mime,
                image_analysis=image_analysis,
            )
            messages: list[dict[str, Any]] = list(
                self._build_messages(text, history, extra_system=extra_system)
            )
            client = self._client()
            temperature = self._config.temperature
            max_tokens = self._config.max_tokens
            thinking = bool(self._config.thinking_enabled)
            reasoning = self._config.reasoning_effort

        orch = AgentOrchestrator()
        try:
            yield from orch.iter_turn(
                messages,
                client,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking_enabled=thinking,
                reasoning_effort=reasoning,
            )
            with self._lock:
                self._last_error = None
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.error("Agent turn failed: %s", exc)
            raise

    def complete(
        self,
        user_message: str,
        history: list[ChatMessage] | None = None,
        *,
        extra_system: str | None = None,
        image_base64: str | None = None,
        image_mime: str | None = None,
        image_analysis: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_configured()
            text = self._prepare_user_message(
                user_message,
                image_base64=image_base64,
                image_mime=image_mime,
                image_analysis=image_analysis,
            )
            messages = self._build_messages(text, history, extra_system=extra_system)
            try:
                result = self._client().chat(
                    messages,
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                    thinking_enabled=bool(self._config.thinking_enabled),
                    reasoning_effort=self._config.reasoning_effort,
                )
                self._last_error = None
                return {
                    "reply": result["content"],
                    "model": result.get("model"),
                    "usage": result.get("usage"),
                }
            except Exception as exc:
                self._last_error = str(exc)
                logger.error("LLM complete failed: %s", exc)
                raise

    def stream_complete(
        self,
        user_message: str,
        history: list[ChatMessage] | None = None,
        *,
        extra_system: str | None = None,
        image_base64: str | None = None,
        image_mime: str | None = None,
        image_analysis: str | None = None,
    ) -> Iterator[str]:
        """流式产出助手回复的文本片段。"""
        with self._lock:
            self._ensure_configured()
            text = self._prepare_user_message(
                user_message,
                image_base64=image_base64,
                image_mime=image_mime,
                image_analysis=image_analysis,
            )
            messages = self._build_messages(text, history, extra_system=extra_system)

        try:
            yield from self._client().chat_stream(
                messages,
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                thinking_enabled=bool(self._config.thinking_enabled),
                reasoning_effort=self._config.reasoning_effort,
            )
            with self._lock:
                self._last_error = None
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.error("LLM stream failed: %s", exc)
            raise


llm_service = LlmService()
