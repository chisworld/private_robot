'use client';

import { motion } from 'framer-motion';
import { Download, PlayCircle, Trash2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/GlassCard';
import { PrimaryButton } from '@/components/ui/PrimaryButton';
import { restoreVariants } from '@/components/ui/motion-presets';

interface TtsPlayerPanelProps {
  audioUrl: string | null;
  lastText: string;
  onClear: () => void;
}

export function TtsPlayerPanel({ audioUrl, lastText, onClear }: TtsPlayerPanelProps) {
  return (
    <motion.div variants={restoreVariants}>
      <GlassCard className="min-h-[420px]">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <PlayCircle className="h-5 w-5 text-indigo-300" />
            <h2 className="text-xl font-semibold tracking-headline text-white">播放预览</h2>
          </div>
          {audioUrl && (
            <PrimaryButton variant="ghost" onClick={onClear} className="inline-flex items-center gap-2 px-4 py-2">
              <Trash2 className="h-4 w-4" />
              清空
            </PrimaryButton>
          )}
        </div>

        {!audioUrl ? (
          <div className="flex min-h-[280px] flex-col items-center justify-center gap-3 text-center">
            <PlayCircle className="h-12 w-12 text-slate-600" />
            <p className="text-sm tracking-wide text-slate-500">合成后的音频将在这里播放</p>
          </div>
        ) : (
          <div className="space-y-6">
            {lastText && (
              <div className="rounded-2xl border border-white/10 bg-slate-900/40 px-5 py-4">
                <p className="mb-1 text-xs uppercase tracking-widest text-slate-400">合成内容</p>
                <p className="text-base leading-relaxed tracking-wide text-slate-100">{lastText}</p>
              </div>
            )}

            <audio controls src={audioUrl} className="w-full" />

            <a
              href={audioUrl}
              download="pnn-tts-output.wav"
              className="inline-flex items-center gap-2 text-sm tracking-wide text-indigo-300 transition-colors hover:text-indigo-200"
            >
              <Download className="h-4 w-4" />
              下载 WAV
            </a>
          </div>
        )}
      </GlassCard>
    </motion.div>
  );
}
