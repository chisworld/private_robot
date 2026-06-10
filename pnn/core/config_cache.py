from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

T = TypeVar("T")


class MtimeJsonConfigCache(Generic[T]):
    """按配置文件 mtime 缓存 load 结果；save 后须 invalidate。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mtime: float = -1.0
        self._value: T | None = None

    def get(self, path: Path, loader: Callable[[], T]) -> T:
        with self._lock:
            mtime = self._file_mtime(path)
            if self._value is not None and mtime == self._mtime:
                return self._copy_value(self._value)
            value = loader()
            self._value = self._copy_value(value)
            self._mtime = mtime
            return self._copy_value(value)

    def invalidate(self) -> None:
        with self._lock:
            self._mtime = -1.0
            self._value = None

    @staticmethod
    def _file_mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime if path.is_file() else 0.0
        except OSError:
            return 0.0

    @staticmethod
    def _copy_value(value: T) -> T:
        return copy.deepcopy(value)
