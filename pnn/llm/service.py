from __future__ import annotations

import logging
import re
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

    def _agent_client(self) -> DeepSeekClient:
        from pnn.llm.config_store import DEFAULT_AGENT_MODEL

        cfg = self._config
        model = (cfg.agent_model or DEFAULT_AGENT_MODEL).strip() or DEFAULT_AGENT_MODEL
        return DeepSeekClient(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model=model,
        )

    def _build_system_messages(self) -> list[ChatMessage]:
        """规则来自 llm.json；角色设定来自当前激活角色包。"""
        from pnn.core.clock import format_clock_system_prompt

        out: list[ChatMessage] = []

        out.append({"role": "system", "content": format_clock_system_prompt()})

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
                "使用长期记忆时须自然融入对话，禁止对用户说「思い出した」「記憶によると」"
                "「根据记忆」「我想起」等元叙述；直接像熟人一样说出内容即可。"
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
        try:
            from pnn.core.clock import build_time_query_system_context

            clk = build_time_query_system_context(user_message)
            if clk:
                parts.append(clk)
        except Exception as exc:
            logger.debug("时钟上下文注入跳过: %s", exc)
        mem = self._memory_context(user_message)
        if mem:
            parts.append(mem)
        extra = (extra_system or "").strip()
        if extra:
            parts.append(extra)
        try:
            from pnn.core.weather_query import build_weather_system_context

            wx = build_weather_system_context(user_message)
            if wx:
                parts.append(wx)
        except Exception as exc:
            logger.debug("天气上下文注入跳过: %s", exc)
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

        from pnn.core.weather_query import sanitize_chat_history_for_weather

        hist = sanitize_chat_history_for_weather(list(history or []), user_message)
        cap = max(2, int(self._config.max_history_messages or 20))
        if len(hist) > cap:
            hist = hist[-cap:]

        for item in hist:
            role = (item.get("role") or "").strip()
            content = (item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        from pnn.core.weather_query import augment_user_message_prefix

        messages.append({"role": "user", "content": augment_user_message_prefix(user_message)})
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

    def _should_use_agent(self, *, connect: bool = True) -> bool:
        try:
            from pnn.launch_apps.service import launch_apps_service

            if launch_apps_service.list_tool_specs():
                return True
            from pnn.mcp.service import mcp_service

            if not mcp_service.chat_enabled():
                return False
            tools = mcp_service.tools_for_openai(connect=False)
            if tools:
                return True
            if not connect:
                return True
            return bool(mcp_service.tools_for_openai(connect=True))
        except Exception as exc:
            logger.debug("MCP Agent 不可用: %s", exc)
            return False

    def agent_enabled(self) -> bool:
        with self._lock:
            self.reload_from_disk()
            return self._should_use_agent(connect=True)

    def agent_enabled_for_config(self) -> bool:
        """设置页/health 用：不触发 MCP connect，避免阻塞 8765。"""
        with self._lock:
            self.reload_from_disk()
            return self._should_use_agent(connect=False)

    def should_use_agent_for_request(
        self,
        user_message: str,
        *,
        image_base64: str | None = None,
        image_analysis: str | None = None,
    ) -> bool:
        """MCP 或快捷启动已开启，且本条消息确实需要工具时才走 Agent。"""
        from pnn.launch_apps.routing import needs_launch_app_task
        from pnn.launch_apps.service import launch_apps_service

        if needs_launch_app_task(user_message) and launch_apps_service.chat_enabled():
            return True
        with self._lock:
            self.reload_from_disk()
            if not self._should_use_agent():
                return False
        from pnn.agent.routing import needs_mcp_agent

        return needs_mcp_agent(
            user_message,
            image_base64=image_base64,
            image_analysis=image_analysis,
        )

    def _log_time_query_if_needed(self, user_message: str) -> None:
        """时间问句：仅记录已注入时钟，台词由 LLM+角色设定生成（通用）。"""
        from pnn.core.clock import format_spoken_time, local_now, user_asks_current_time

        if not user_asks_current_time(user_message):
            return
        logger.info(
            "[clock] 已注入本机时刻，交由 LLM+角色设定转述: %s (%s)",
            (user_message or "")[:80],
            format_spoken_time(local_now(), lang="zh"),
        )

    def _log_weather_query_if_needed(self, user_message: str) -> None:
        """天气问句：仅记录 MSN 已注入 LLM，台词由角色设定生成（通用）。"""
        from pnn.core.weather_query import user_asks_weather

        if not user_asks_weather(user_message):
            return
        logger.info(
            "[weather] 已注入 MSN 数据，交由 LLM+角色设定转述: %s",
            (user_message or "")[:80],
        )

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

        self._log_time_query_if_needed(user_message)
        self._log_weather_query_if_needed(user_message)

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
            client = self._agent_client()
            temperature = self._config.temperature
            max_tokens = self._config.max_tokens
            # 工具调用时 client 内会关闭 thinking（与 DeepSeek API 限制一致）
            thinking = False
            reasoning = self._config.reasoning_effort
            logger.info(
                "Agent 请求模型: %s（日常闲聊 model=%s）",
                client.model,
                self._config.model,
            )

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
        self._log_time_query_if_needed(user_message)
        self._log_weather_query_if_needed(user_message)

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

    def collect_complete(
        self,
        user_message: str,
        history: list[ChatMessage] | None = None,
        *,
        extra_system: str | None = None,
        image_base64: str | None = None,
        image_mime: str | None = None,
        image_analysis: str | None = None,
    ) -> str:
        """收集完整回复（用于天气问句缓冲后再润色下发）。"""
        parts: list[str] = []
        for delta in self.stream_complete(
            user_message,
            history,
            extra_system=extra_system,
            image_base64=image_base64,
            image_mime=image_mime,
            image_analysis=image_analysis,
        ):
            parts.append(delta)
        return "".join(parts)

    def finalize_weather_reply(
        self,
        draft: str,
        user_message: str,
        history: list[ChatMessage] | None = None,
        *,
        extra_system: str | None = None,
    ) -> str:
        """天气问句：剔除播报腔；必要时二次润色。"""
        from pnn.core.weather_query import (
            build_weather_polish_instruction,
            is_bad_weather_reply,
            user_asks_weather,
        )

        text = (draft or "").strip()
        if not text or not user_asks_weather(user_message):
            return draft
        if not is_bad_weather_reply(text):
            return draft
        logger.info("[weather] 检测到播报腔，进行二次润色")
        try:
            polished = self._polish_weather_reply(
                text,
                user_message,
                history,
                extra_system=extra_system,
            )
            if polished and not is_bad_weather_reply(polished):
                return polished
        except Exception as exc:
            logger.warning("天气润色失败，回退初稿: %s", exc)
        return self._strip_bad_weather_sentences(text)

    @staticmethod
    def _strip_bad_weather_sentences(text: str) -> str:
        from pnn.core.weather_query import is_bad_weather_reply

        parts = re.split(r"(?<=[。！？!?])", text or "")
        kept = [p for p in parts if p.strip() and not is_bad_weather_reply(p)]
        joined = "".join(kept).strip()
        return joined or (text or "").strip()

    def _polish_weather_reply(
        self,
        draft: str,
        user_message: str,
        history: list[ChatMessage] | None,
        *,
        extra_system: str | None = None,
    ) -> str:
        from pnn.core.weather_query import (
            augment_user_message_prefix,
            build_weather_polish_instruction,
            build_weather_system_context,
        )

        with self._lock:
            self._ensure_configured()
            messages: list[ChatMessage] = list(self._build_system_messages())
            wx = build_weather_system_context(user_message)
            polish = build_weather_polish_instruction(draft=draft)
            sys_parts = [p for p in (wx, polish) if p]
            if sys_parts:
                messages.append({"role": "system", "content": "\n\n".join(sys_parts)})
            extra = (extra_system or "").strip()
            if extra:
                messages.append({"role": "system", "content": extra})
            messages.append(
                {
                    "role": "user",
                    "content": augment_user_message_prefix(user_message),
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": "[weather-polish] 只输出重写后的最终台词，不要解释。",
                }
            )
            temperature = self._config.temperature
            max_tokens = min(int(self._config.max_tokens or 1024), 768)

        result = self._client().chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_enabled=False,
            reasoning_effort=self._config.reasoning_effort,
        )
        return (result.get("content") or "").strip()

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
        self._log_time_query_if_needed(user_message)
        self._log_weather_query_if_needed(user_message)

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
