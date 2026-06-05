"""API 侧阻塞任务线程池（独立于 asyncio 默认 executor，避免 shutdown 竞态）。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_pool: ThreadPoolExecutor | None = None


def init_blocking_pool(*, max_workers: int = 16) -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pnn-api")
    return _pool


def shutdown_blocking_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


async def run_blocking(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_running_loop()
    if loop.is_closed():
        raise RuntimeError("API event loop 已关闭")
    pool = _pool
    if pool is None:
        raise RuntimeError("API is shutting down")
    return await loop.run_in_executor(pool, partial(func, *args, **kwargs))
