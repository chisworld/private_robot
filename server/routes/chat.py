from __future__ import annotations

import asyncio
import json
import logging
import threading

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from pnn.core.blocking import run_blocking
from pnn.llm.service import llm_service
from pnn.memory.service import memory_service

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 启动器/桌宠据此判断 8765 进程是否过旧；升级对话/MCP 逻辑后请递增
STREAM_SSE_VERSION = 29


class ChatHistoryItem(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = ""


class ChatCompletionRequest(BaseModel):
    message: str = ""
    history: list[ChatHistoryItem] = Field(default_factory=list)
    # 桌宠：注入 14酱 表情列表，要求模型在句首输出【表情:名称】
    pet_expression_prompt: str | None = None
    image_base64: str | None = None
    image_mime: str | None = Field(default="image/png")
    image_analysis: str | None = None
    # 桌宠语音模式：流式结束后不写记忆，由客户端在 TTS 播完后再写
    defer_memory: bool = False

    @model_validator(mode="after")
    def _sanitize_and_require(self) -> ChatCompletionRequest:
        if not (self.message or "").strip() and not (self.image_base64 or "").strip():
            raise ValueError("消息与截图不能同时为空")
        pruned: list[ChatHistoryItem] = []
        for item in self.history:
            role = (item.role or "").strip()
            content = (item.content or "").strip()
            if role in ("user", "assistant") and content:
                pruned.append(ChatHistoryItem(role=role, content=content))
        self.history = pruned
        return self


class LlmConfigUpdate(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    agent_model: str | None = None
    system_prompt: str | None = None
    active_character: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=64, le=8192)
    max_history_messages: int | None = Field(default=None, ge=2, le=100)
    thinking_enabled: bool | None = None
    reasoning_effort: str | None = Field(default=None, pattern="^(high|max)$")
    vision_model: str | None = None
    vision_base_url: str | None = None
    vision_api_key: str | None = None
    nsfw_enabled: bool | None = None
    local_chat_lite: bool | None = None
    local_model_base_url: str | None = None
    local_model: str | None = None
    local_model_api_key: str | None = None


class CharacterUpdate(BaseModel):
    name: str | None = None
    character_prompt: str | None = None


class CharacterCreate(BaseModel):
    id: str = Field(min_length=1)
    name: str = ""
    character_prompt: str = ""


@router.get("/config")
async def get_config() -> dict:
    cfg = llm_service.get_config()
    cfg["stream_sse_version"] = STREAM_SSE_VERSION
    cfg["agent_enabled"] = llm_service.agent_enabled_for_config()
    return cfg


@router.post("/config/reload")
async def reload_config() -> dict:
    await run_blocking(llm_service.reload_from_disk)
    cfg = llm_service.get_config()
    cfg["stream_sse_version"] = STREAM_SSE_VERSION
    return cfg


@router.get("/characters")
async def list_characters() -> dict:
    return {"characters": llm_service.list_characters()}


@router.get("/characters/{char_id}")
async def get_character(char_id: str) -> dict:
    try:
        return llm_service.get_character(char_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/characters/{char_id}")
async def put_character(char_id: str, body: CharacterUpdate) -> dict:
    try:
        return await run_blocking(
            llm_service.save_character,
            char_id,
            name=body.name,
            character_prompt=body.character_prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/characters")
async def create_character(body: CharacterCreate) -> dict:
    try:
        return await run_blocking(
            llm_service.save_character,
            body.id,
            name=body.name or body.id,
            character_prompt=body.character_prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/config")
async def update_config(body: LlmConfigUpdate) -> dict:
    # exclude_none 仅去掉未传字段；空字符串的 system_prompt 也要原样保存
    payload = body.model_dump(exclude_none=True)
    if body.system_prompt is not None:
        payload["system_prompt"] = body.system_prompt
    cfg = llm_service.update_config(**payload)
    cfg["stream_sse_version"] = STREAM_SSE_VERSION
    return cfg


@router.post("/completions")
async def chat_completions(body: ChatCompletionRequest) -> dict:
    history = [item.model_dump() for item in body.history]
    try:
        result = await run_blocking(
            llm_service.complete,
            body.message,
            history,
            extra_system=body.pet_expression_prompt,
            image_base64=body.image_base64,
            image_mime=body.image_mime,
            image_analysis=body.image_analysis,
        )
        reply = result.get("reply") or ""
        if reply.strip() and not body.defer_memory:
            threading.Thread(
                target=memory_service.after_conversation_turn,
                args=(body.message, reply, history),
                daemon=True,
            ).start()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/completions/stream")
async def chat_completions_stream(body: ChatCompletionRequest) -> StreamingResponse:
    """SSE 流式输出。须在单一线程内消费 requests 流，避免 iterate_in_threadpool 跨线程断流。"""
    history = [item.model_dump() for item in body.history]
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()

    def _safe_put(kind: str, payload: str | None) -> None:
        try:
            asyncio.run_coroutine_threadsafe(queue.put((kind, payload)), loop)
        except RuntimeError:
            # 事件循环已关闭（客户端断开），丢弃消息
            pass

    def worker() -> None:
        chunks: list[str] = []
        try:
            from pnn.agent.routing import needs_mcp_agent
            from pnn.core.weather_query import user_asks_weather

            is_weather_query = user_asks_weather(body.message) and not (
                body.image_base64 or ""
            ).strip()
            needs_tools = needs_mcp_agent(
                body.message,
                image_base64=body.image_base64,
                image_analysis=body.image_analysis,
            )
            use_agent = (
                False
                if is_weather_query
                else llm_service.should_use_agent_for_request(
                    body.message,
                    image_base64=body.image_base64,
                    image_analysis=body.image_analysis,
                )
            )
            if is_weather_query:
                from pnn.core.weather_query import (
                    prime_weather_for_message,
                    weather_status_json,
                )

                wx_snap = prime_weather_for_message(body.message)
                _safe_put("weather_status", weather_status_json(wx_snap, body.message))
                logger.info(
                    "对话走 Playwright/MSN 天气注入+角色口吻 LLM: %s | %s",
                    (body.message or "")[:80],
                    wx_snap.line or "无数据",
                )
            from pnn.agent.code_direct import try_direct_workspace_read_reply

            direct_read = try_direct_workspace_read_reply(body.message)
            route_info = llm_service.describe_request_route(
                body.message,
                use_agent=use_agent,
                direct_read=bool(direct_read),
                needs_tools=needs_tools and not use_agent,
                is_weather=is_weather_query,
                image_base64=body.image_base64,
                image_analysis=body.image_analysis,
            )
            _safe_put("llm_route", json.dumps(route_info, ensure_ascii=False))
            if direct_read:
                logger.info(
                    "对话走代码文件直达读取: %s",
                    (body.message or "")[:80],
                )
                chunk = 24
                for i in range(0, len(direct_read), chunk):
                    part = direct_read[i : i + chunk]
                    chunks.append(part)
                    _safe_put("delta", part)
            elif use_agent:
                logger.info("对话走 Agent+MCP: %s", (body.message or "")[:80])
                for kind, payload in llm_service.iter_agent_events(
                    body.message,
                    history,
                    extra_system=body.pet_expression_prompt,
                    image_base64=body.image_base64,
                    image_mime=body.image_mime,
                    image_analysis=body.image_analysis,
                ):
                    if kind == "status" and payload:
                        _safe_put("agent_status", payload)
                    elif kind == "delta" and payload:
                        chunks.append(payload)
                        _safe_put("delta", payload)
            elif needs_tools:
                msg = (
                    "MCP 未就绪，无法使用浏览器搜索。"
                    "请在设置→MCP 中启用对话并连接 Playwright 后重试。"
                )
                logger.warning(
                    "本条需要 MCP 工具但未就绪，已拒绝普通对话回退: %s",
                    (body.message or "")[:80],
                )
                _safe_put("agent_status", msg)
                _safe_put("error", msg)
                return
            else:
                if is_weather_query:
                    draft = llm_service.collect_complete(
                        body.message,
                        history,
                        extra_system=body.pet_expression_prompt,
                        image_base64=body.image_base64,
                        image_mime=body.image_mime,
                        image_analysis=body.image_analysis,
                    )
                    full = llm_service.finalize_weather_reply(
                        draft,
                        body.message,
                        history,
                        extra_system=body.pet_expression_prompt,
                    )
                    if full:
                        chunks.append(full)
                        _safe_put("delta", full)
                else:
                    for delta in llm_service.stream_complete(
                        body.message,
                        history,
                        extra_system=body.pet_expression_prompt,
                        image_base64=body.image_base64,
                        image_mime=body.image_mime,
                        image_analysis=body.image_analysis,
                    ):
                        chunks.append(delta)
                        _safe_put("delta", delta)
            full = "".join(chunks)
            if full.strip() and not body.defer_memory:
                threading.Thread(
                    target=memory_service.after_conversation_turn,
                    args=(body.message, full, history),
                    daemon=True,
                ).start()
            _safe_put("done", None)
        except ValueError as exc:
            _safe_put("error", str(exc))
        except Exception as exc:
            _safe_put("error", str(exc))

    threading.Thread(target=worker, daemon=True).start()

    async def event_generator():
        keepalive_s = 15.0
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=keepalive_s)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if kind == "error":
                yield _sse_event({"error": payload or "对话失败"})
                break
            if kind == "done":
                yield _sse_event({"done": True})
                break
            if kind == "agent_status":
                yield _sse_event({"agent_status": payload or ""})
                continue
            if kind == "weather_status":
                yield _sse_event({"weather_status": payload or ""})
                continue
            if kind == "llm_route":
                try:
                    route_obj = json.loads(payload or "{}")
                except json.JSONDecodeError:
                    route_obj = {"route": payload or ""}
                yield _sse_event({"llm_route": route_obj})
                continue
            yield _sse_event({"delta": payload or ""})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
