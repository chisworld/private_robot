from __future__ import annotations

import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pnn.llm.service import llm_service
from pnn.memory.service import memory_service

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 启动器据此判断 8765 上的进程是否含流式修复；升级后请递增
STREAM_SSE_VERSION = 4


class ChatHistoryItem(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1)


class ChatCompletionRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatHistoryItem] = Field(default_factory=list)
    # 桌宠：注入 14酱 表情列表，要求模型在句首输出【表情:名称】
    pet_expression_prompt: str | None = None


class LlmConfigUpdate(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    active_character: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=64, le=8192)
    max_history_messages: int | None = Field(default=None, ge=2, le=100)


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
    return cfg


@router.post("/config/reload")
async def reload_config() -> dict:
    await asyncio.to_thread(llm_service.reload_from_disk)
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
        return await asyncio.to_thread(
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
        return await asyncio.to_thread(
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
        result = await asyncio.to_thread(
            llm_service.complete,
            body.message,
            history,
            extra_system=body.pet_expression_prompt,
        )
        reply = result.get("reply") or ""
        if reply.strip():
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
            for delta in llm_service.stream_complete(
                body.message,
                history,
                extra_system=body.pet_expression_prompt,
            ):
                chunks.append(delta)
                _safe_put("delta", delta)
            full = "".join(chunks)
            if full.strip():
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
        while True:
            kind, payload = await queue.get()
            if kind == "error":
                yield _sse_event({"error": payload or "对话失败"})
                break
            if kind == "done":
                yield _sse_event({"done": True})
                break
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
