"""MCP 专用 asyncio 线程（供同步 FastAPI 路由调用）。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()

_owner_queue: asyncio.Queue[
    tuple[Callable[[], Coroutine[Any, Any, Any]], concurrent.futures.Future[Any]]
] | None = None
_owner_task: asyncio.Task[None] | None = None
_owner_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread
    with _lock:
        if _loop is not None and _loop.is_running():
            return _loop

        ready = threading.Event()
        err: list[BaseException] = []

        def _runner() -> None:
            global _loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                _loop = loop
                ready.set()
                loop.run_forever()
            except BaseException as exc:
                err.append(exc)
                ready.set()

        t = threading.Thread(target=_runner, name="pnn-mcp-asyncio", daemon=True)
        _thread = t
        t.start()
        ready.wait(timeout=30.0)
        if err:
            raise err[0]
        if _loop is None:
            raise RuntimeError("MCP 事件循环启动失败")
        return _loop


async def _owner_worker() -> None:
    assert _owner_queue is not None
    while True:
        make_coro, cfut = await _owner_queue.get()
        try:
            val = await make_coro()
            if not cfut.done():
                cfut.set_result(val)
        except BaseException as exc:
            if not cfut.done():
                cfut.set_exception(exc)


def _ensure_owner_worker(loop: asyncio.AbstractEventLoop) -> None:
    global _owner_queue, _owner_task
    with _owner_lock:
        if _owner_task is not None and not _owner_task.done():
            return

        async def _bootstrap() -> None:
            global _owner_queue, _owner_task
            _owner_queue = asyncio.Queue()
            _owner_task = asyncio.create_task(_owner_worker())

        asyncio.run_coroutine_threadsafe(_bootstrap(), loop).result(timeout=30.0)


def run_mcp_coro(coro: Coroutine[Any, Any, T], *, timeout: float = 120.0) -> T:
    loop = _ensure_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)


def run_on_bridge_owner(
    make_coro: Callable[[], Coroutine[Any, Any, T]],
    *,
    timeout: float = 120.0,
) -> T:
    loop = _ensure_loop()
    _ensure_owner_worker(loop)
    assert _owner_queue is not None
    cfut: concurrent.futures.Future[T] = concurrent.futures.Future()

    async def _enqueue() -> None:
        await _owner_queue.put((make_coro, cfut))

    asyncio.run_coroutine_threadsafe(_enqueue(), loop).result(timeout=min(60.0, timeout))
    return cfut.result(timeout=timeout)


def shutdown_mcp_runtime(*, timeout: float = 30.0) -> None:
    global _loop, _thread, _owner_queue, _owner_task
    loop = _loop
    if loop is None or not loop.is_running():
        return
    try:
        loop.call_soon_threadsafe(loop.stop)
    except Exception:
        logger.debug("MCP loop stop", exc_info=True)
    if _thread is not None:
        _thread.join(timeout=timeout)
    _loop = None
    _thread = None
    _owner_queue = None
    _owner_task = None
