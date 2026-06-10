"""构建日志尾部检测（编译成功/失败）。"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_FAIL_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"BUILD FAILED",
        r"build failed",
        r"Compilation failed",
        r"error TS\d+",
        r"npm ERR!",
        r"FAILED \(",
        r"pytest.*failed",
        r"\d+ errors?",
        r"SyntaxError:",
        r"ModuleNotFoundError:",
        r"AssertionError",
        r"MSB\d+.*error",
        r": error ",
    )
)
_SUCCESS_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"BUILD SUCCESS",
        r"Compiled successfully",
        r"webpack compiled successfully",
        r"Build succeeded",
        r"0 errors?",
        r"tests? passed",
        r"All tests passed",
    )
)

_RESOLVE_CACHE_TTL_SEC = 60.0


@dataclass
class BuildScanState:
    path: str
    mtime: float = 0.0
    size: int = 0
    last_fail_at: datetime | None = None
    last_success_at: datetime | None = None


@dataclass
class _WatchCache:
    paths_key: tuple[str, ...] = ()
    files: list[Path] = field(default_factory=list)
    refreshed_at: float = 0.0


def _tail_text(path: Path, *, max_bytes: int = 16000) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size <= 0:
        return ""
    try:
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, 2)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def classify_build_tail(text: str) -> str | None:
    body = (text or "").strip()
    if not body:
        return None
    tail = body[-4000:]
    fail_score = sum(1 for p in _FAIL_PATTERNS if p.search(tail))
    ok_score = sum(1 for p in _SUCCESS_PATTERNS if p.search(tail))
    if fail_score and fail_score >= ok_score:
        return "failed"
    if ok_score and ok_score > 0:
        return "success"
    return None


class BuildLogWatcher:
    def __init__(self, paths: list[str]) -> None:
        self._paths = [str(p).strip() for p in paths if str(p).strip()]
        self._states: dict[str, BuildScanState] = {}
        self._watch_cache = _WatchCache()

    def set_paths(self, paths: list[str]) -> None:
        self._paths = [str(p).strip() for p in paths if str(p).strip()]
        self._watch_cache = _WatchCache()

    @staticmethod
    def _resolve_watch_files(raw: str) -> list[Path]:
        """配置项可为单个日志文件，或项目目录（自动扫描 *.log）。"""
        path = Path(raw).expanduser()
        if path.is_file():
            return [path]
        if not path.is_dir():
            return []
        files: list[Path] = []
        seen: set[str] = set()
        candidates: list[Path] = list(path.glob("*.log"))
        for sub in ("logs", "log", "build", "dist", ".gradle", "target", "out"):
            subp = path / sub
            if subp.is_dir():
                candidates.extend(subp.rglob("*.log"))
        if not candidates:
            candidates = list(path.rglob("*.log"))
        for p in candidates:
            if not p.is_file():
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            files.append(p)
            if len(files) >= 32:
                break
        return files

    def _watch_files(self) -> list[Path]:
        key = tuple(self._paths)
        now = time.monotonic()
        cache = self._watch_cache
        if (
            cache.files
            and cache.paths_key == key
            and now - cache.refreshed_at < _RESOLVE_CACHE_TTL_SEC
        ):
            return cache.files
        files: list[Path] = []
        for raw in self._paths:
            files.extend(self._resolve_watch_files(raw))
        cache.paths_key = key
        cache.files = files
        cache.refreshed_at = now
        return files

    def poll(self) -> str | None:
        """返回 'failed' | 'success' | None（无新变化）。"""
        event: str | None = None
        for path in self._watch_files():
            key = str(path.resolve())
            try:
                st = path.stat()
            except OSError:
                continue
            state = self._states.get(key)
            if state is None:
                self._states[key] = BuildScanState(path=key, mtime=st.st_mtime, size=st.st_size)
                continue
            if st.st_mtime == state.mtime and st.st_size == state.size:
                continue
            state.mtime = st.st_mtime
            state.size = st.st_size
            kind = classify_build_tail(_tail_text(path))
            if kind == "failed":
                state.last_fail_at = datetime.now()
                event = "failed"
            elif kind == "success":
                state.last_success_at = datetime.now()
                event = "success"
        return event
