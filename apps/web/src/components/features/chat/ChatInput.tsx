'use client';

import { useCallback, useEffect, useState } from 'react';
import { Loader2, Mic, MicOff, Send, Volume2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { GlassCard } from '@/components/ui/GlassCard';
import { GlassTextarea } from '@/components/ui/GlassInput';
import { PrimaryButton } from '@/components/ui/PrimaryButton';
import { restoreVariants } from '@/components/ui/motion-presets';
import { cn } from '@/lib/cn';
import type { TtsSpeakMode } from '@/lib/api';

interface ChatInputProps {
  loading: boolean;
  speaking: boolean;
  streaming: boolean;
  asrPartial: string;
  asrInputText: string;
  asrStarting: boolean;
  autoSpeak: boolean;
  onAutoSpeakChange: (value: boolean) => void;
  ttsSpeakMode: TtsSpeakMode;
  onTtsSpeakModeChange: (mode: TtsSpeakMode) => void;
  onSend: (text: string) => Promise<void>;
  onSpeakLast?: (text: string) => Promise<void>;
  onAsrStart: () => Promise<void>;
  onAsrStop: () => Promise<void>;
  lastAssistantText?: string;
}

export function ChatInput({
  loading,
  speaking,
  streaming,
  asrPartial,
  asrInputText,
  asrStarting,
  autoSpeak,
  onAutoSpeakChange,
  ttsSpeakMode,
  onTtsSpeakModeChange,
  onSend,
  onSpeakLast,
  onAsrStart,
  onAsrStop,
  lastAssistantText,
}: ChatInputProps) {
  const [text, setText] = useState('');

  // final 只进 lines、会清空 partial；必须用 asrInputText（lines + partial）
  useEffect(() => {
    if (streaming) {
      setText(asrInputText);
      return;
    }
    if (asrInputText.trim()) {
      setText(asrInputText);
    }
  }, [asrInputText, streaming]);

  const handleSend = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setText('');
    await onSend(trimmed);
  }, [onSend, text]);

  const toggleMic = useCallback(async () => {
    if (streaming) {
      const draft = asrInputText.trim() || text.trim();
      await onAsrStop();
      if (draft) setText(draft);
      if (draft && !loading) {
        setText('');
        await onSend(draft);
      }
      return;
    }
    await onAsrStart();
  }, [asrInputText, loading, onAsrStart, onAsrStop, onSend, streaming, text]);

  return (
    <motion.div variants={restoreVariants} className="col-span-12">
      <GlassCard>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-semibold tracking-headline text-white">输入</h2>
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex cursor-pointer items-center gap-2 text-xs tracking-wide text-slate-400">
              <input
                type="checkbox"
                checked={autoSpeak}
                onChange={(e) => onAutoSpeakChange(e.target.checked)}
                className="rounded border-white/20 bg-slate-900/60 text-indigo-500"
              />
              自动朗读
            </label>
            <div
              className={cn(
                'flex rounded-xl border border-white/10 bg-slate-900/50 p-0.5 text-xs tracking-wide',
                !autoSpeak && 'pointer-events-none opacity-40',
              )}
            >
              <button
                type="button"
                onClick={() => onTtsSpeakModeChange('sentence')}
                className={cn(
                  'rounded-lg px-3 py-1.5 transition',
                  ttsSpeakMode === 'sentence'
                    ? 'bg-indigo-500/40 text-indigo-100'
                    : 'text-slate-400 hover:text-slate-200',
                )}
              >
                分句朗读
              </button>
              <button
                type="button"
                onClick={() => onTtsSpeakModeChange('full')}
                className={cn(
                  'rounded-lg px-3 py-1.5 transition',
                  ttsSpeakMode === 'full'
                    ? 'bg-indigo-500/40 text-indigo-100'
                    : 'text-slate-400 hover:text-slate-200',
                )}
              >
                整段朗读
              </button>
            </div>
          </div>
        </div>

        <GlassTextarea
          label="消息"
          value={text}
          disabled={loading || streaming}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
          placeholder={
            streaming
              ? '正在听写… 再次点击麦克风结束并发送'
              : '输入文字，Enter 发送，Shift+Enter 换行'
          }
          className="min-h-[100px]"
        />

        {streaming && (
          <p className="mt-2 text-xs tracking-wide text-indigo-300/90">
            {asrInputText
              ? `识别中：${asrInputText}`
              : asrPartial
                ? `识别中：${asrPartial}`
                : '麦克风已开启，请说话…'}
          </p>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void toggleMic()}
            disabled={loading || asrStarting}
            className={cn(
              'inline-flex items-center gap-2 rounded-2xl border px-5 py-3 text-sm font-medium tracking-wide transition-all duration-300',
              streaming
                ? 'border-red-400/40 bg-red-500/20 text-red-100'
                : 'border-white/10 bg-slate-900/60 text-slate-200 hover:border-indigo-400/40',
              'disabled:cursor-not-allowed disabled:opacity-50',
            )}
          >
            {asrStarting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : streaming ? (
              <MicOff className="h-4 w-4" />
            ) : (
              <Mic className="h-4 w-4" />
            )}
            {streaming ? '结束并发送' : '语音输入 (ASR)'}
          </button>

          <PrimaryButton
            onClick={() => void handleSend()}
            disabled={loading || !text.trim()}
            className="inline-flex items-center gap-2"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {loading ? '发送中…' : '发送'}
          </PrimaryButton>

          {lastAssistantText && onSpeakLast && (
            <button
              type="button"
              onClick={() => void onSpeakLast(lastAssistantText)}
              disabled={speaking || loading}
              className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-slate-900/60 px-5 py-3 text-sm tracking-wide text-slate-300 transition hover:text-white disabled:opacity-50"
            >
              {speaking ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Volume2 className="h-4 w-4" />
              )}
              重播语音
            </button>
          )}
        </div>
      </GlassCard>
    </motion.div>
  );
}
