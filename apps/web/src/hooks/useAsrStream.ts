'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  asrApi,
  backendErrorMessage,
  createAsrWebSocket,
  waitForBackend,
  type AsrConfig,
  type AsrWsMessage,
} from '@/lib/api';

export interface TranscriptLine {
  id: string;
  text: string;
  kind: 'partial' | 'final';
  at: number;
}

const ACTIVE_STATUSES = new Set(['loading', 'listening', 'speech']);

export interface UseAsrStreamOptions {
  /** 语音对话页：final 写入输入框；启动时清空本轮听写缓存 */
  forChat?: boolean;
}

export function useAsrStream(options?: UseAsrStreamOptions) {
  const forChat = options?.forChat ?? false;
  const [config, setConfig] = useState<AsrConfig | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [starting, setStarting] = useState(false);
  const [status, setStatus] = useState('idle');
  const [partial, setPartial] = useState('');
  const [lines, setLines] = useState<TranscriptLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [activeThreshold, setActiveThreshold] = useState(0.03);
  const [isSpeech, setIsSpeech] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const smoothLevelRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  const pushLevel = useCallback((energy: number, threshold: number, speech: boolean) => {
    smoothLevelRef.current = smoothLevelRef.current * 0.55 + energy * 0.45;
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      setAudioLevel(smoothLevelRef.current);
      setActiveThreshold(threshold);
      setIsSpeech(speech);
    });
  }, []);

  const applyStatus = useCallback((next: string) => {
    setStatus(next);
    setStreaming(ACTIVE_STATUSES.has(next));
    setStarting(next === 'loading');
    if (next === 'idle' || next === 'error') {
      setStarting(false);
    }
  }, []);

  const handleWsMessage = useCallback(
    (msg: AsrWsMessage) => {
      if (msg.type === 'status') {
        applyStatus(msg.status);
        return;
      }
      if (msg.type === 'error') {
        setError(msg.message);
        applyStatus('error');
        return;
      }
      if (msg.type === 'partial') {
        setPartial(msg.text);
        return;
      }
      if (msg.type === 'final') {
        const text = (msg.text || '').trim();
        setPartial('');
        if (text) {
          setLines((prev) => [
            ...prev,
            { id: `${Date.now()}-${prev.length}`, text, kind: 'final', at: Date.now() },
          ]);
        }
        return;
      }
      if (msg.type === 'level') {
        pushLevel(msg.energy, msg.threshold, msg.is_speech);
      }
    },
    [applyStatus, pushLevel],
  );

  /** 对话页输入框：已确认的 final + 当前 partial（ASR 页 final 只进 lines 列表） */
  const inputText = useMemo(() => {
    const committed = lines.map((l) => l.text).join('');
    if (!partial) return committed;
    return committed + partial;
  }, [lines, partial]);

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
        const cfg = await asrApi.getConfig();
        if (cancelled) return;
        setConfig(cfg);
        applyStatus(cfg.status);
        if (cfg.last_error) setError(cfg.last_error);
      } catch {
        if (!cancelled) setError('后端已启动但加载配置失败，请刷新页面。');
      }
    })();

    const ws = createAsrWebSocket(handleWsMessage);
    wsRef.current = ws;
    return () => {
      cancelled = true;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      ws.close();
    };
  }, [applyStatus, handleWsMessage]);

  const refreshConfig = useCallback(async () => {
    const next = await asrApi.getConfig();
    setConfig(next);
    applyStatus(next.status);
    if (next.last_error) setError(next.last_error);
    return next;
  }, [applyStatus]);

  const updateConfig = useCallback(async (patch: Partial<AsrConfig>) => {
    setSaving(true);
    setError(null);
    try {
      const next = await asrApi.updateConfig(patch);
      setConfig(next);
      return next;
    } catch (e) {
      const message = e instanceof Error ? e.message : '配置更新失败';
      setError(message);
      throw e;
    } finally {
      setSaving(false);
    }
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setStarting(true);
    if (forChat) {
      setLines([]);
      setPartial('');
    }
    applyStatus('loading');
    try {
      const res = await asrApi.startStream();
      applyStatus(res.status);
    } catch (e) {
      const message = e instanceof Error ? e.message : '启动失败';
      setError(message);
      applyStatus('error');
    }
  }, [applyStatus, forChat]);

  const stop = useCallback(async () => {
    setError(null);
    try {
      await asrApi.stopStream();
      setPartial('');
      smoothLevelRef.current = 0;
      setAudioLevel(0);
      setIsSpeech(false);
      applyStatus('idle');
    } catch (e) {
      setError(e instanceof Error ? e.message : '停止失败');
    }
  }, [applyStatus]);

  const updateThreshold = useCallback(async (value: number | null) => {
    try {
      const next = await asrApi.updateConfig({ energy_threshold: value });
      setConfig(next);
      if (value !== null) setActiveThreshold(value);
    } catch (e) {
      setError(e instanceof Error ? e.message : '阈值更新失败');
    }
  }, []);

  const transcribeFile = useCallback(async (file: File) => {
    setError(null);
    setStarting(true);
    try {
      const result = await asrApi.transcribeFile(file);
      setLines((prev) => [
        ...prev,
        { id: `${Date.now()}-file`, text: result.text, kind: 'final', at: Date.now() },
      ]);
      return result;
    } catch (e) {
      const message = e instanceof Error ? e.message : '转写失败';
      setError(message);
      throw e;
    } finally {
      setStarting(false);
    }
  }, []);

  const clearLines = useCallback(() => {
    setLines([]);
    setPartial('');
  }, []);

  return {
    config,
    streaming,
    starting,
    status,
    partial,
    inputText,
    lines,
    error,
    saving,
    audioLevel,
    activeThreshold,
    isSpeech,
    updateConfig,
    updateThreshold,
    refreshConfig,
    start,
    stop,
    transcribeFile,
    clearLines,
  };
}
