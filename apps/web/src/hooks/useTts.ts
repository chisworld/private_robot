'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ttsApi, type LanguageOption, type TtsConfig } from '@/lib/api';

export function useTts() {
  const [config, setConfig] = useState<TtsConfig | null>(null);
  const [serverAlive, setServerAlive] = useState(false);
  const [languages, setLanguages] = useState<LanguageOption[]>([]);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [synthesizing, setSynthesizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [lastText, setLastText] = useState('');
  const audioUrlRef = useRef<string | null>(null);

  const revokeAudioUrl = useCallback(() => {
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    const health = await ttsApi.health();
    setServerAlive(health.ok);
    if (health.error) {
      setError((prev) => prev ?? health.error ?? null);
    }
    return health;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await ttsApi.getConfig();
        if (cancelled) return;
        setConfig(cfg);
        setServerAlive(cfg.server_alive);
        if (cfg.service_version !== undefined && cfg.service_version < 2) {
          setError('TTS 后端版本过旧，请关闭旧 API 窗口后重新运行 start.bat');
        }
      } catch {
        if (!cancelled) {
          setError(
            '无法连接 TTS 后端（8765）。请关闭旧窗口后双击 start.bat，等待「API 已就绪」。',
          );
        }
      }
    })();
    ttsApi.getLanguages().then((data) => setLanguages(data.languages));
    return () => {
      cancelled = true;
      revokeAudioUrl();
    };
  }, [revokeAudioUrl]);

  useEffect(() => {
    if (serverAlive) return;
    const timer = window.setInterval(() => {
      void refreshHealth();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [serverAlive, refreshHealth]);

  const updateConfig = useCallback(async (patch: Partial<TtsConfig>) => {
    setSaving(true);
    setError(null);
    try {
      const next = await ttsApi.updateConfig(patch);
      setConfig(next);
      const health = await refreshHealth();
      setServerAlive(health.ok);
      if (!health.ok && next.auto_start_server && next.work_path) {
        setError(
          (prev) =>
            prev ??
            '配置已保存，但 GPT-SoVITS 未连接。请点击「保存并启动服务」或等待自动启动完成。',
        );
      }
      return next;
    } catch (e) {
      const message = e instanceof Error ? e.message : '配置保存失败';
      setError(message);
      throw e;
    } finally {
      setSaving(false);
    }
  }, [refreshHealth]);

  const startServer = useCallback(async () => {
    setStarting(true);
    setError(null);
    try {
      const kick = await ttsApi.startServer();
      if (kick.ok) {
        setServerAlive(true);
        return kick;
      }
      for (let i = 0; i < 120; i += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        const health = await refreshHealth();
        if (health.ok) {
          return health;
        }
      }
      const message = 'TTS 服务启动超时（首次加载模型约需 1–2 分钟），请稍后再试';
      setError(message);
      throw new Error(message);
    } catch (e) {
      const message = e instanceof Error ? e.message : '启动失败';
      setError(message);
      throw e;
    } finally {
      setStarting(false);
    }
  }, [refreshHealth]);

  useEffect(() => {
    if (!config || serverAlive || config.provider === 'cosyvoice') return;
    if (!config.auto_start_server || !config.work_path) return;
    setError('GPT-SoVITS 未连接，正在尝试自动启动…');
    void startServer().catch(() => undefined);
  }, [config, serverAlive, startServer]);

  const synthesize = useCallback(
    async (text: string, emotionId?: string) => {
      if (!text.trim()) {
        setError('请输入要合成的文本');
        return;
      }
      setSynthesizing(true);
      setError(null);
      try {
        const blob = await ttsApi.synthesize(text, config?.text_lang, emotionId);
        revokeAudioUrl();
        const url = URL.createObjectURL(blob);
        audioUrlRef.current = url;
        setAudioUrl(url);
        setLastText(text.trim());
      } catch (e) {
        const message = e instanceof Error ? e.message : '合成失败';
        setError(message);
        throw e;
      } finally {
        setSynthesizing(false);
      }
    },
    [config?.text_lang, revokeAudioUrl],
  );

  const clearAudio = useCallback(() => {
    revokeAudioUrl();
    setAudioUrl(null);
    setLastText('');
  }, [revokeAudioUrl]);

  return {
    config,
    serverAlive,
    languages,
    saving,
    starting,
    synthesizing,
    error,
    audioUrl,
    lastText,
    updateConfig,
    startServer,
    refreshHealth,
    synthesize,
    clearAudio,
  };
}
