from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")

# 持久线程池，避免 asyncio 默认 executor 在部分环境下被提前 shutdown
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="pnn-sync")


async def run_sync(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """在线程池中运行阻塞调用，避免阻塞 asyncio 事件循环。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_EXECUTOR, lambda: func(*args, **kwargs))
