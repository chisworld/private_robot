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
            from pnn.llm.routing import is_cloud_api_key, local_llm_ready

            cfg["configured"] = is_cloud_api_key(self._config.api_key) or local_llm_ready(
                self._config
            )
            cfg["last_error"] = self._last_error
            cfg["characters"] = self.list_characters()
            try:
                from pnn.llm.local_qwen import local_llm_health
                from pnn.llm.vision_client import DASHSCOPE_VL_MODELS, vision_configured

                cfg["vision_configured"] = vision_configured()
                cfg["vision_model_options"] = [m for m, _ in DASHSCOPE_VL_MODELS]
                ok, detail = local_llm_health(self._config.local_model_base_url)
                cfg["local_model_available"] = ok
                cfg["local_model_status"] = detail
            except Exception:
                cfg["vision_configured"] = False
                cfg["vision_model_options"] = []
                cfg["local_model_available"] = False
                cfg["local_model_status"] = ""
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

    @staticmethod
    def _is_cloud_api_key(key: str) -> bool:
        from pnn.llm.routing import is_cloud_api_key

        return is_cloud_api_key(key)

    def _cloud_client(self, *, model: str | None = None) -> DeepSeekClient:
        cfg = self._config
        return DeepSeekClient(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model=(model or cfg.model),
        )

    def _local_nsfw_client(self) -> DeepSeekClient:
        cfg = self._config
        base = (cfg.local_model_base_url or "http://127.0.0.1:8080").strip().rstrip("/")
        model = (cfg.local_model or "qwen3.6").strip() or "qwen3.6"
        key = (cfg.local_model_api_key or "local").strip() or "local"
        return DeepSeekClient(api_key=key, base_url=base, model=model)

    def _chat_client(
        self,
        user_message: str,
        *,
        image_base64: str | None = None,
        image_mime: str | None = None,
        image_analysis: str | None = None,
    ) -> DeepSeekClient:
        from pnn.llm.routing import should_use_local_chat

        if should_use_local_chat(
            self._config,
            user_message,
            image_base64=image_base64,
            image_analysis=image_analysis,
        ):
            return self._local_nsfw_client()
        return self._cloud_client()

    def _client(self) -> DeepSeekClient:
        return self._cloud_client()

    def _agent_client(self) -> DeepSeekClient:
        from pnn.llm.config_store import DEFAULT_AGENT_MODEL

        cfg = self._config
        model = (cfg.agent_model or DEFAULT_AGENT_MODEL).strip() or DEFAULT_AGENT_MODEL
        return self._cloud_client(model=model)

    def _build_system_messages(self, *, local_lite: bool = False) -> list[ChatMessage]:
        """规则来自 llm.json；角色设定来自当前激活角色包。"""
        char_id = (self._config.active_character or "").strip()
        if local_lite:
            from pnn.llm.local_qwen import (
                compact_local_chat_grounding_rules,
                local_lite_character_max_chars,
            )

            out: list[ChatMessage] = []
            out.append({"role": "system", "content": compact_local_chat_grounding_rules()})
            lang = self._reply_language_rule_short(char_id)
            if lang:
                out.append({"role": "system", "content": lang})
            try:
                from pnn.characters.pack import load_pack
                from pnn.characters.reply_lang import normalize_reply_language
                from pnn.pet.bilingual_reply import llm_bilingual_output_rule

                pack = load_pack(char_id) if char_id else None
                lang_code = normalize_reply_language(pack.reply_language if pack else "ja")
                bi_rule = llm_bilingual_output_rule(lang_code)
                if bi_rule:
                    out.append({"role": "system", "content": bi_rule})
            except Exception:
                pass
            if char_id:
                try:
                    ch = load_character(char_id)
                except (ValueError, OSError) as exc:
                    logger.warning("加载角色 %s 失败: %s", char_id, exc)
                    ch = None
                if ch and ch.character_prompt.strip():
                    label = ch.name or ch.id
                    prompt = ch.character_prompt.strip()
                    cap = local_lite_character_max_chars()
                    if len(prompt) > cap:
                        prompt = prompt[:cap].rstrip() + "\n…（本地精简模式已截断角色设定）"
                    out.append(
                        {
                            "role": "system",
                            "content": (
                                f"【角色设定：{label}·口吻参考】\n"
                                "以下为人设背景；回复内容须以用户最新消息为准，勿脱离话题。\n"
                                f"{prompt}"
                            ),
                        }
                    )
            return out

        from pnn.core.clock import format_clock_system_prompt

        out: list[ChatMessage] = []

        out.append({"role": "system", "content": format_clock_system_prompt()})

        # 语言规则放在最前面，避免被长角色设定淹没
        lang_rule = self._reply_language_rule(char_id)
        if lang_rule:
            out.append({"role": "system", "content": lang_rule})
        try:
            from pnn.characters.pack import load_pack
            from pnn.characters.reply_lang import normalize_reply_language
            from pnn.pet.bilingual_reply import llm_bilingual_output_rule

            pack = load_pack(char_id) if char_id else None
            lang_code = normalize_reply_language(pack.reply_language if pack else "ja")
            bi_rule = llm_bilingual_output_rule(lang_code)
            if bi_rule:
                out.append({"role": "system", "content": bi_rule})
        except Exception:
            pass

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

    def _reply_language_rule_short(self, char_id: str) -> str:
        try:
            from pnn.characters.pack import load_pack
            from pnn.characters.reply_lang import is_chinese, is_japanese, normalize_reply_language

            pack = load_pack(char_id) if char_id else None
        except Exception:
            pack = None
        lang = normalize_reply_language(pack.reply_language if pack else "ja")
        if is_japanese(lang):
            return "【语言】朗读段用日语；末尾须另起一行【中文】写同义简体中文。"
        if is_chinese(lang):
            return "【语言】你必须用简体中文回复。"
        return ""

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
                "【最重要规则 - 回复语言】你只能用日语（日本語）写朗读段。"
                "即使用户用中文提问，朗读段也必须是日语。"
                "同时必须另起一行写【中文】并提供同义简体中文（界面与记忆用，不要朗读）。"
                "使用长期记忆时须自然融入对话，禁止对用户说「思い出した」「記憶によると」"
                "「根据记忆」「我想起」等元叙述；直接像熟人一样说出内容即可。"
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
        self,
        user_message: str,
        extra_system: str | None,
        *,
        for_local: bool = False,
        lite: bool = False,
    ) -> str | None:
        parts: list[str] = []
        try:
            from pnn.core.clock import build_time_query_system_context

            clk = build_time_query_system_context(user_message)
            if clk:
                parts.append(clk)
        except Exception as exc:
            logger.debug("时钟上下文注入跳过: %s", exc)
        if not (for_local and lite):
            mem = self._memory_context(user_message)
            if mem:
                if for_local:
                    from pnn.llm.local_qwen import local_memory_max_chars

                    cap = local_memory_max_chars(lite=lite)
                    if cap and len(mem) > cap:
                        mem = mem[:cap].rstrip() + "\n…（本地模式已截断部分记忆以加速推理）"
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

    @staticmethod
    def _local_output_format_reminder() -> str:
        return (
            "【本地模型输出格式 — 必须与 DeepSeek 相同】\n"
            "每句完整句子句首按顺序写完整标签（用户界面不显示）：\n"
            "【情绪:标签id】【表情:名称】【动作:名称】（动作可省略）。\n"
            "禁止写成【:soft】【:skirt_side】等省略形式；"
            "禁止自造中文标签名；标签不得出现在朗读正文中。\n"
            "禁止输出括号内动作/神态描写或第三人称旁白；只写角色说出口的台词。"
            "非中文角色须在朗读段后另起一行【中文】写简体中文版（格式与 DeepSeek 相同）。"
        )

    def _augment_extra_system_for_local(
        self,
        extra_system: str | None,
        user_message: str,
        *,
        image_base64: str | None = None,
        image_analysis: str | None = None,
    ) -> str | None:
        from pnn.llm.local_qwen import build_local_lite_extra_system, local_chat_lite_enabled
        from pnn.llm.routing import should_use_local_chat

        if not should_use_local_chat(
            self._config,
            user_message,
            image_base64=image_base64,
            image_analysis=image_analysis,
        ):
            return extra_system
        if local_chat_lite_enabled(self._config.local_chat_lite):
            return build_local_lite_extra_system(extra_system)
        note = self._local_output_format_reminder()
        extra = (extra_system or "").strip()
        return f"{extra}\n\n{note}" if extra else note

    @staticmethod
    def _resolve_local_chat_limits(
        cfg: Any,
        use_local: bool,
    ) -> tuple[bool, int | None, int]:
        """返回 (lite, history_cap, max_tokens)。"""
        if not use_local:
            return False, None, int(cfg.max_tokens or 8192)
        from pnn.llm.local_qwen import (
            local_chat_lite_enabled,
            local_chat_max_history,
            local_chat_max_tokens,
        )

        lite = local_chat_lite_enabled(cfg.local_chat_lite)
        hist_cap = local_chat_max_history(cfg.max_history_messages, lite=lite)
        max_tok = local_chat_max_tokens(lite=lite)
        return lite, hist_cap, max_tok

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
        history_cap: int | None = None,
        for_local: bool = False,
        lite: bool = False,
    ) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        messages.extend(self._build_system_messages(local_lite=for_local and lite))
        merged = self._merge_extra_system(
            user_message, extra_system, for_local=for_local, lite=lite
        )
        if merged:
            messages.append({"role": "system", "content": merged})

        from pnn.core.weather_query import sanitize_chat_history_for_weather

        hist = sanitize_chat_history_for_weather(list(history or []), user_message)
        cap = history_cap
        if cap is None:
            cap = max(2, int(self._config.max_history_messages or 20))
        cap = max(2, int(cap))
        if for_local and lite:
            from pnn.llm.local_qwen import build_local_anti_echo_hint, trim_history_for_local_llm

            hist = trim_history_for_local_llm(hist, cap=cap, lite=True)
            echo = build_local_anti_echo_hint(hist)
            if echo:
                messages.append({"role": "system", "content": echo})
        elif len(hist) > cap:
            hist = hist[-cap:]

        for item in hist:
            role = (item.get("role") or "").strip()
            content = (item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        if for_local and lite:
            from pnn.core.clock import user_asks_current_time
            from pnn.core.weather_query import augment_user_message_prefix, user_asks_weather

            body = (user_message or "").strip()
            if user_asks_current_time(body) or user_asks_weather(body):
                user_content = augment_user_message_prefix(body)
            else:
                user_content = body
            if body:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"【本轮用户消息】「{body[:480]}」"
                            "——请直接回应此内容，勿偏题或编造用户未提及的事。"
                        ),
                    }
                )
        else:
            from pnn.core.weather_query import augment_user_message_prefix

            user_content = augment_user_message_prefix(user_message)
        messages.append({"role": "user", "content": user_content})
        return messages

    def reload_from_disk(self) -> None:
        """每次对话前从 llm.json / .env 重新加载，确保刚保存的配置立即生效。"""
        from pnn.core.env import load_env
        from pnn.llm.config_store import _llm_config_cache

        load_env(force=True)
        _llm_config_cache.invalidate()
        with self._lock:
            self._config = load_llm_config()

    def _ensure_configured(
        self,
        *,
        for_agent: bool = False,
        user_message: str = "",
        image_base64: str | None = None,
        image_analysis: str | None = None,
    ) -> None:
        self.reload_from_disk()
        from pnn.llm.local_qwen import local_llm_health
        from pnn.llm.routing import should_use_local_chat

        use_local = should_use_local_chat(
            self._config,
            user_message,
            use_agent=for_agent,
            image_base64=image_base64,
            image_analysis=image_analysis,
        )
        if for_agent:
            if not self._is_cloud_api_key(self._config.api_key):
                raise ValueError(
                    "未配置 DeepSeek API Key（MCP/Agent 需要）。"
                    "请在设置 → LLM 填写，或在 .env 设置 DEEPSEEK_API_KEY。"
                )
        elif use_local:
            ok, detail = local_llm_health(self._config.local_model_base_url)
            if not ok:
                raise ValueError(
                    f"本地 Qwen 未就绪（{detail}）。"
                    "模型正在后台加载，请稍后再试，或查看 data/logs/qwen_boot.log"
                )
        elif not self._is_cloud_api_key(self._config.api_key):
            raise ValueError(
                "未配置 DeepSeek API Key。请在设置 → LLM 填写，"
                "或在角色页开启 NSFW 使用本地 Qwen，"
                "或在 .env 设置 DEEPSEEK_API_KEY。"
            )

    def _should_use_agent(self, *, connect: bool = True) -> bool:
        try:
            from pnn.launch_apps.service import launch_apps_service

            if launch_apps_service.list_tool_specs():
                return True
            from pnn.system_control.service import system_control_service

            if system_control_service.list_tool_specs():
                return True
            from pnn.clipboard.service import clipboard_service

            if clipboard_service.list_tool_specs():
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
        """MCP 或本机助手已开启，且本条消息需要 Agent 时返回 True。"""
        from pnn.agent.local_assistant import should_route_local_assistant_to_agent
        from pnn.agent.routing import needs_mcp_agent
        from pnn.llm.routing import use_local_nsfw_chat
        from pnn.memory.sanitize import is_system_proactive_turn

        if is_system_proactive_turn(user_message):
            return False

        needs_tools = needs_mcp_agent(
            user_message,
            image_base64=image_base64,
            image_analysis=image_analysis,
        )

        with self._lock:
            self.reload_from_disk()
            cfg = self._config

        # NSFW 日常闲聊优先本地 Qwen，不因「桌宠助手/MCP 已开」被误判为 Agent
        if use_local_nsfw_chat(
            cfg,
            user_message,
            use_agent=False,
            image_base64=image_base64,
            image_analysis=image_analysis,
        ) and not needs_tools:
            return False

        local_assistant = should_route_local_assistant_to_agent(user_message)
        # 纯闲聊：勿 connect MCP（否则每条消息都可能卡住数分钟）
        if not needs_tools and not local_assistant:
            return False

        with self._lock:
            if not self._should_use_agent(connect=False):
                return False
        return needs_tools or local_assistant

    def describe_request_route(
        self,
        user_message: str,
        *,
        use_agent: bool = False,
        direct_read: bool = False,
        needs_tools: bool = False,
        is_weather: bool = False,
        image_base64: str | None = None,
        image_analysis: str | None = None,
    ) -> dict[str, str | bool]:
        """返回本条对话将使用的路由（终端 / SSE）。"""
        from pnn.llm.routing import describe_chat_route

        with self._lock:
            self.reload_from_disk()
            cfg = self._config
        if direct_read:
            return {
                "route": "code_direct",
                "label": "本地代码文件读取",
                "model": "",
                "base_url": "",
                "nsfw_enabled": bool(cfg.nsfw_enabled),
            }
        if use_agent:
            return describe_chat_route(
                cfg,
                user_message,
                use_agent=True,
                image_base64=image_base64,
                image_analysis=image_analysis,
            )
        if needs_tools:
            return {
                "route": "mcp_blocked",
                "label": "需要 MCP（未就绪）",
                "model": (cfg.agent_model or cfg.model or "").strip(),
                "base_url": (cfg.base_url or "").strip(),
                "nsfw_enabled": bool(cfg.nsfw_enabled),
            }
        info = describe_chat_route(
            cfg,
            user_message,
            use_agent=False,
            image_base64=image_base64,
            image_analysis=image_analysis,
        )
        if is_weather:
            info = dict(info)
            info["weather"] = True
        return info

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
            self._ensure_configured(
                for_agent=True,
                user_message=user_message,
                image_base64=image_base64,
                image_analysis=image_analysis,
            )
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
            self._ensure_configured(
                user_message=user_message,
                image_base64=image_base64,
                image_analysis=image_analysis,
            )
            text = self._prepare_user_message(
                user_message,
                image_base64=image_base64,
                image_mime=image_mime,
                image_analysis=image_analysis,
            )
            extra = self._augment_extra_system_for_local(
                extra_system,
                user_message,
                image_base64=image_base64,
                image_analysis=image_analysis,
            )
            from pnn.llm.routing import should_use_local_chat

            use_local = should_use_local_chat(
                self._config,
                user_message,
                image_base64=image_base64,
                image_analysis=image_analysis,
            )
            lite, hist_cap, max_tok = self._resolve_local_chat_limits(
                self._config, use_local
            )
            messages = self._build_messages(
                text,
                history,
                extra_system=extra,
                history_cap=hist_cap,
                for_local=use_local,
                lite=lite,
            )
            client = self._chat_client(
                user_message,
                image_base64=image_base64,
                image_analysis=image_analysis,
            )
            try:
                result = client.chat(
                    messages,
                    temperature=self._config.temperature,
                    max_tokens=max_tok,
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
            self._ensure_configured(user_message=user_message)
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
            client = self._chat_client(user_message)

        result = client.chat(
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
            self._ensure_configured(
                user_message=user_message,
                image_base64=image_base64,
                image_analysis=image_analysis,
            )
            text = self._prepare_user_message(
                user_message,
                image_base64=image_base64,
                image_mime=image_mime,
                image_analysis=image_analysis,
            )
            extra = self._augment_extra_system_for_local(
                extra_system,
                user_message,
                image_base64=image_base64,
                image_analysis=image_analysis,
            )
            from pnn.llm.local_qwen import estimate_prompt_chars
            from pnn.llm.routing import should_use_local_chat

            use_local = should_use_local_chat(
                self._config,
                user_message,
                image_base64=image_base64,
                image_analysis=image_analysis,
            )
            lite, hist_cap, max_tokens = self._resolve_local_chat_limits(
                self._config, use_local
            )
            messages = self._build_messages(
                text,
                history,
                extra_system=extra,
                history_cap=hist_cap,
                for_local=use_local,
                lite=lite,
            )
            client = self._chat_client(
                user_message,
                image_base64=image_base64,
                image_analysis=image_analysis,
            )
            temperature = self._config.temperature
            # 桌宠流式闲聊：关闭 V4 思考模式，避免长时间只有 reasoning 无 content 像卡死
            thinking = False
            reasoning = self._config.reasoning_effort

            if use_local:
                mode = "精简" if lite else "标准"
                logger.info(
                    "对话走本地 Qwen(%s): model=%s prompt≈%s字 history≤%s max_tokens=%s",
                    mode,
                    client.model,
                    estimate_prompt_chars(messages),
                    hist_cap,
                    max_tokens,
                )
            else:
                logger.info("对话走 DeepSeek: model=%s", client.model)

        try:
            yield from client.chat_stream(
                messages,
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
            logger.error("LLM stream failed: %s", exc)
            raise


llm_service = LlmService()
