"""记忆 [dialogue] 块内助手台词译中。"""

from __future__ import annotations

import re

_MERGE_SEP = re.compile(r"\n\n---\n\n+")


def translate_assistant_lines_in_block(
    body: str,
    *,
    user_label: str,
    assistant_label: str,
) -> str:
    """仅翻译 assistant_label 行；user 行保持原样。"""
    from pnn.translate.service import translate_service

    text = (body or "").strip()
    if not text:
        return text
    blocks = _MERGE_SEP.split(text) if _MERGE_SEP.search(text) else [text]
    u_prefix = f"{user_label}："
    a_prefix = f"{assistant_label}："
    out_blocks: list[str] = []
    for block in blocks:
        lines: list[str] = []
        for line in block.splitlines():
            raw = line.strip()
            if raw.startswith(a_prefix):
                seg = raw[len(a_prefix) :].strip()
                if seg:
                    seg = translate_service.for_memory_storage(seg)
                lines.append(f"{a_prefix}{seg}")
            else:
                lines.append(line.rstrip())
        out_blocks.append("\n".join(lines).strip())
    return "\n\n---\n\n".join(out_blocks).strip()
