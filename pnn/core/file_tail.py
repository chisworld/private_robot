from __future__ import annotations

from pathlib import Path


def read_tail_text(
    path: Path,
    *,
    max_lines: int = 12,
    block_size: int = 8192,
) -> str:
    """从文件末尾读取最后 max_lines 行，避免整文件 read_text。"""
    if max_lines <= 0 or not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            end = handle.tell()
            if end == 0:
                return ""
            buffer = b""
            pos = end
            line_count = 0
            while pos > 0 and line_count <= max_lines:
                read_size = min(block_size, pos)
                pos -= read_size
                handle.seek(pos)
                buffer = handle.read(read_size) + buffer
                line_count = buffer.count(b"\n")
            text = buffer.decode("utf-8", errors="replace")
            lines = text.splitlines()
            if not lines:
                return ""
            return "\n".join(lines[-max_lines:])
    except OSError:
        return ""
