/** 从流式缓冲区提取可送去 TTS 的完整句子（降低首句朗读延迟）。 */

/** 仅在句末断句；逗号/顿号不断，避免朗读时频繁停顿 */
const SENTENCE_END = /[。！？!?\n]/;
const MIN_CHUNK_LEN = 6;

export function pullTtsChunks(buffer: string, spokenOffset: number): {
  chunks: string[];
  nextOffset: number;
} {
  const pending = buffer.slice(spokenOffset);
  if (!pending.trim()) {
    return { chunks: [], nextOffset: spokenOffset };
  }

  const chunks: string[] = [];
  let cursor = 0;
  let lastEnd = 0;

  while (cursor < pending.length) {
    const ch = pending[cursor] ?? '';
    if (SENTENCE_END.test(ch)) {
      const piece = pending.slice(lastEnd, cursor + 1).trim();
      if (piece.length >= MIN_CHUNK_LEN) {
        chunks.push(piece);
        lastEnd = cursor + 1;
      }
    }
    cursor += 1;
  }

  return { chunks, nextOffset: spokenOffset + lastEnd };
}

export function pullFinalTtsChunk(buffer: string, spokenOffset: number): {
  chunk: string | null;
  nextOffset: number;
} {
  const tail = buffer.slice(spokenOffset).trim();
  if (!tail || tail.length < MIN_CHUNK_LEN) {
    return { chunk: null, nextOffset: buffer.length };
  }
  return { chunk: tail, nextOffset: buffer.length };
}
