'use client';

import { motion } from 'framer-motion';
import { Bot, User } from 'lucide-react';
import { GlassCard } from '@/components/ui/GlassCard';
import { restoreVariants } from '@/components/ui/motion-presets';
import type { ChatMessage } from '@/lib/api';
import { cn } from '@/lib/cn';

interface ChatMessageListProps {
  messages: ChatMessage[];
  loading: boolean;
  streaming: boolean;
}

export function ChatMessageList({ messages, loading, streaming }: ChatMessageListProps) {
  return (
    <motion.div variants={restoreVariants} className="col-span-12 lg:col-span-8">
      <GlassCard className="flex min-h-[420px] flex-col">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold tracking-headline text-white">对话记录</h2>
          <span className="text-xs tracking-wide text-slate-500">{messages.length} 条消息</span>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto pr-1">
          {messages.length === 0 && !loading && !streaming && (
            <p className="py-16 text-center text-sm tracking-wide text-slate-500">
              输入文字或按住麦克风说话，开始与 DeepSeek 对话。
            </p>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                'flex gap-3',
                msg.role === 'user' ? 'flex-row-reverse' : 'flex-row',
              )}
            >
              <div
                className={cn(
                  'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl',
                  msg.role === 'user'
                    ? 'bg-indigo-500/30 text-indigo-200'
                    : 'bg-emerald-500/20 text-emerald-200',
                )}
              >
                {msg.role === 'user' ? (
                  <User className="h-4 w-4" />
                ) : (
                  <Bot className="h-4 w-4" />
                )}
              </div>
              <div
                className={cn(
                  'max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed tracking-wide',
                  msg.role === 'user'
                    ? 'bg-indigo-500/20 text-indigo-50'
                    : 'border border-white/10 bg-slate-900/50 text-slate-100',
                )}
              >
                {msg.content || (msg.streaming ? '' : '…')}
                {msg.streaming && (
                  <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-emerald-400 align-middle" />
                )}
              </div>
            </div>
          ))}

          {loading && !streaming && messages.every((m) => !m.streaming) && (
            <div className="flex gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/20">
                <Bot className="h-4 w-4 animate-pulse text-emerald-200" />
              </div>
              <div className="rounded-2xl border border-white/10 bg-slate-900/50 px-4 py-3 text-sm text-slate-400">
                正在连接模型…
              </div>
            </div>
          )}
        </div>
      </GlassCard>
    </motion.div>
  );
}
