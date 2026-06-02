'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  backendErrorMessage,
  chatApi,
  ttsApi,
  waitForBackend,
  type ChatMessage,
  type LlmConfig,
  type TtsSpeakMode,
} from '@/lib/api';
import { readTtsSpeakMode, writeTtsSpeakMode } from '@/lib/chat-preferences';
import { pullFinalTtsChunk, pullTtsChunks } from '@/lib/tts-chunks';

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(true);
  const [ttsSpeakMode, setTtsSpeakModeState] = useState<TtsSpeakMode>('sentence');
  const [error, setError] = useState<string | null>(null);
  const [savingConfig, setSavingConfig] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const ttsPendingRef = useRef<string[]>([]);
  const ttsRunIdRef = useRef(0);
  const ttsDrainingRef = useRef(false);
  const streamBufferRef = useRef('');
  const ttsOffsetRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const pendingAssistantIdRef = useRef<string | null>(null);

  const revokeAudioUrl = useCallback(() => {
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
  }, []);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    revokeAudioUrl();
  }, [revokeAudioUrl]);

  const playBlob = useCallback(
    async (blob: Blob, options?: { interrupt?: boolean }) => {
      const interrupt = options?.interrupt !== false;
      if (interrupt) {
        stopAudio();
      } else {
        revokeAudioUrl();
      }
      const url = URL.createObjectURL(blob);
      audioUrlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      await new Promise<void>((resolve, reject) => {
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error('音频播放失败'));
        void audio.play().catch(reject);
      });
    },
    [revokeAudioUrl, stopAudio],
  );

  const resetTtsQueue = useCallback(() => {
    ttsRunIdRef.current += 1;
    ttsPendingRef.current = [];
  }, []);

  const drainTtsQueue = useCallback(
    async (runId: number) => {
      if (ttsDrainingRef.current) return;
      ttsDrainingRef.current = true;
      setSpeaking(true);
      let firstSegment = true;
      try {
        let prefetch: Promise<Blob> | null = null;
        while (ttsPendingRef.current.length > 0 && runId === ttsRunIdRef.current) {
          const text = ttsPendingRef.current.shift()!;
          const blobPromise = prefetch ?? ttsApi.synthesize(text);
          const nextText = ttsPendingRef.current[0];
          prefetch =
            nextText && runId === ttsRunIdRef.current
              ? ttsApi.synthesize(nextText)
              : null;
          const blob = await blobPromise;
          if (runId !== ttsRunIdRef.current) break;
          await playBlob(blob, { interrupt: firstSegment });
          firstSegment = false;
        }
      } catch (e) {
        const message = e instanceof Error ? e.message : '语音合成失败';
        setError(message);
      } finally {
        ttsDrainingRef.current = false;
        if (ttsPendingRef.current.length > 0 && runId === ttsRunIdRef.current) {
          void drainTtsQueue(runId);
        } else if (runId === ttsRunIdRef.current) {
          setSpeaking(false);
        }
      }
    },
    [playBlob],
  );

  const enqueueTts = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      ttsPendingRef.current.push(trimmed);
      void drainTtsQueue(ttsRunIdRef.current);
    },
    [drainTtsQueue],
  );

  const flushTtsFromBuffer = useCallback(
    (buffer: string, final = false) => {
      const { chunks, nextOffset } = pullTtsChunks(buffer, ttsOffsetRef.current);
      ttsOffsetRef.current = nextOffset;
      for (const chunk of chunks) {
        enqueueTts(chunk);
      }
      if (final) {
        const { chunk, nextOffset: end } = pullFinalTtsChunk(buffer, ttsOffsetRef.current);
        ttsOffsetRef.current = end;
        if (chunk) enqueueTts(chunk);
      }
    },
    [enqueueTts],
  );

  const scheduleUiUpdate = useCallback((assistantId: string, content: string) => {
    streamBufferRef.current = content;
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const text = streamBufferRef.current;
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? { ...m, content: text } : m)),
      );
    });
  }, []);

  useEffect(() => {
    setTtsSpeakModeState(readTtsSpeakMode());
  }, []);

  const setTtsSpeakMode = useCallback((mode: TtsSpeakMode) => {
    setTtsSpeakModeState(mode);
    writeTtsSpeakMode(mode);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const probe = await waitForBackend();
      if (cancelled) return;
      if (!probe.ok) {
        setError(backendErrorMessage(probe));
        return;
      }
      try {
        setLlmConfig(await chatApi.getConfig());
        setError(null);
      } catch (e) {
        if (!cancelled) {
          const detail = e instanceof Error ? e.message : '';
          setError(
            detail
              ? `配置加载失败：${detail}`
              : '配置加载失败，请关闭旧窗口后重新运行 start.bat 再刷新。',
          );
        }
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      stopAudio();
    };
  }, [stopAudio]);

  const reloadLlmConfig = useCallback(async () => {
    try {
      const cfg = await chatApi.reloadConfig();
      setLlmConfig(cfg);
      return cfg;
    } catch {
      const cfg = await chatApi.getConfig();
      setLlmConfig(cfg);
      return cfg;
    }
  }, []);

  const refreshConfig = useCallback(async () => reloadLlmConfig(), [reloadLlmConfig]);

  const updateLlmConfig = useCallback(async (patch: Partial<LlmConfig> & { api_key?: string }) => {
    setSavingConfig(true);
    setError(null);
    try {
      await chatApi.updateConfig(patch);
      return await reloadLlmConfig();
    } catch (e) {
      const message = e instanceof Error ? e.message : '配置保存失败';
      setError(message);
      throw e;
    } finally {
      setSavingConfig(false);
    }
  }, [reloadLlmConfig]);

  const speakText = useCallback(
    async (text: string) => {
      ttsOffsetRef.current = 0;
      streamBufferRef.current = '';
      stopAudio();
      resetTtsQueue();
      const runId = ttsRunIdRef.current;
      enqueueTts(text);
      while (
        (ttsPendingRef.current.length > 0 || ttsDrainingRef.current) &&
        runId === ttsRunIdRef.current
      ) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, 80));
      }
    },
    [enqueueTts, resetTtsQueue, stopAudio],
  );

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading || streaming) return;

      setError(null);
      setLoading(true);
      setStreaming(true);
      stopAudio();
      resetTtsQueue();
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      streamBufferRef.current = '';
      ttsOffsetRef.current = 0;

      const userMsg: ChatMessage = {
        id: `u-${Date.now()}`,
        role: 'user',
        content: trimmed,
        at: Date.now(),
      };

      const assistantId = `a-${Date.now()}`;
      pendingAssistantIdRef.current = assistantId;
      const assistantPlaceholder: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        at: Date.now(),
        streaming: true,
      };

      setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);

      const history = [...messages, userMsg].map((m) => ({
        role: m.role,
        content: m.content,
      }));

      let fullReply = '';

      try {
        await reloadLlmConfig();
        const { reply } = await chatApi.complete(
          trimmed,
          history.slice(0, -1),
          abortRef.current.signal,
        );
        fullReply = (reply || '').trim();

        if (!fullReply) {
          setError('模型未返回内容，请检查 API Key 或网络后重试。');
          setMessages((prev) => prev.filter((m) => m.id !== assistantId));
          return;
        }

        const chars = [...fullReply];
        for (let i = 0; i < chars.length; i += 1) {
          if (abortRef.current?.signal.aborted) return;
          const partial = chars.slice(0, i + 1).join('');
          scheduleUiUpdate(assistantId, partial);
          if (autoSpeak && ttsSpeakMode === 'sentence') {
            flushTtsFromBuffer(partial, false);
          }
          await new Promise<void>((resolve) => {
            window.setTimeout(resolve, 18);
          });
        }

        if (rafRef.current !== null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
        }

        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: fullReply, streaming: false }
              : m,
          ),
        );

        if (autoSpeak) {
          if (ttsSpeakMode === 'full') {
            ttsOffsetRef.current = 0;
            enqueueTts(fullReply);
          } else {
            flushTtsFromBuffer(fullReply, true);
          }
        }
      } catch (e) {
        if (e instanceof Error && e.name === 'AbortError') {
          return;
        }
        const message = e instanceof Error ? e.message : '对话请求失败';
        setError(message);
        setMessages((prev) =>
          prev.filter((m) => m.id !== userMsg.id && m.id !== assistantId),
        );
      } finally {
        pendingAssistantIdRef.current = null;
        setLoading(false);
        setStreaming(false);
      }
    },
    [
      autoSpeak,
      enqueueTts,
      flushTtsFromBuffer,
      loading,
      messages,
      resetTtsQueue,
      scheduleUiUpdate,
      stopAudio,
      streaming,
      reloadLlmConfig,
      ttsSpeakMode,
    ],
  );

  const clearMessages = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    stopAudio();
    resetTtsQueue();
  }, [resetTtsQueue, stopAudio]);

  return {
    messages,
    llmConfig,
    loading,
    streaming,
    speaking,
    autoSpeak,
    setAutoSpeak,
    ttsSpeakMode,
    setTtsSpeakMode,
    error,
    savingConfig,
    sendMessage,
    speakText,
    clearMessages,
    updateLlmConfig,
    refreshConfig,
    stopAudio,
  };
}
