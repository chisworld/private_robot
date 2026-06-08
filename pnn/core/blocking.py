"""API 侧阻塞任务线程池（独立于 asyncio 默认 executor，避免 shutdown 竞态）。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_pool: ThreadPoolExecutor | None = None
_heavy_pool: ThreadPoolExecutor | None = None


def init_blocking_pool(
    *,
    max_workers: int = 10,
    heavy_workers: int = 2,
) -> ThreadPoolExecutor:
    global _pool, _heavy_pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pnn-api")
    if _heavy_pool is None:
        _heavy_pool = ThreadPoolExecutor(
            max_workers=heavy_workers, thread_name_prefix="pnn-heavy"
        )
    return _pool


def shutdown_blocking_pool() -> None:
    global _pool, _heavy_pool
    for pool in (_pool, _heavy_pool):
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
    _pool = None
    _heavy_pool = None


async def run_blocking(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_running_loop()
    if loop.is_closed():
        raise RuntimeError("API event loop 已关闭")
    pool = _pool
    if pool is None:
        raise RuntimeError("API is shutting down")
    return await loop.run_in_executor(pool, partial(func, *args, **kwargs))


async def run_blocking_heavy(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """TTS 合成/预热/角色包应用等长任务，避免占满通用线程池。"""
    loop = asyncio.get_running_loop()
    if loop.is_closed():
        raise RuntimeError("API event loop 已关闭")
    pool = _heavy_pool
    if pool is None:
        raise RuntimeError("API is shutting down")
    return await loop.run_in_executor(pool, partial(func, *args, **kwargs))
