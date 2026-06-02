"""从流式回复中提取可 TTS 的完整句子（与 Web tts-chunks.ts 一致）。"""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"[。！？!?\n]")
_MIN_CHUNK_LEN = 6


def pull_tts_chunks(buffer: str, spoken_offset: int) -> tuple[list[str], int]:
    pending = buffer[spoken_offset:]
    if not pending.strip():
        return [], spoken_offset

    chunks: list[str] = []
    cursor = 0
    last_end = 0

    while cursor < len(pending):
        ch = pending[cursor]
        if _SENTENCE_END.match(ch):
            piece = pending[last_end : cursor + 1].strip()
            if len(piece) >= _MIN_CHUNK_LEN:
                chunks.append(piece)
                last_end = cursor + 1
        cursor += 1

    return chunks, spoken_offset + last_end


def pull_final_tts_chunk(buffer: str, spoken_offset: int) -> tuple[str | None, int]:
    tail = buffer[spoken_offset:].strip()
    if not tail or len(tail) < _MIN_CHUNK_LEN:
        return None, len(buffer)
    return tail, len(buffer)
