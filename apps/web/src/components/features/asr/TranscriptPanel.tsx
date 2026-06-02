'use client';

import { motion } from 'framer-motion';
import { FileText, Trash2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/GlassCard';
import { PrimaryButton } from '@/components/ui/PrimaryButton';
import { restoreVariants } from '@/components/ui/motion-presets';
import type { TranscriptLine } from '@/hooks/useAsrStream';

interface TranscriptPanelProps {
  lines: TranscriptLine[];
  partial: string;
  onClear: () => void;
}

export function TranscriptPanel({ lines, partial, onClear }: TranscriptPanelProps) {
  return (
    <motion.div variants={restoreVariants} className="col-span-12 lg:col-span-8">
      <GlassCard className="min-h-[480px]">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <FileText className="h-5 w-5 text-emerald-300" />
            <h2 className="text-xl font-semibold tracking-headline text-white">识别结果</h2>
          </div>
          <PrimaryButton variant="ghost" onClick={onClear} className="inline-flex items-center gap-2 px-4 py-2">
            <Trash2 className="h-4 w-4" />
            清空
          </PrimaryButton>
        </div>

        <div className="max-h-[560px] space-y-4 overflow-y-auto pr-2">
          {lines.length === 0 && !partial && (
            <p className="py-16 text-center text-sm tracking-wide text-slate-500">
              识别文字将显示在这里…
            </p>
          )}

          {lines.map((line) => (
            <motion.div
              key={line.id}
              initial={{ opacity: 0, y: 8, filter: 'blur(8px)' }}
              animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
              className="rounded-2xl border border-white/10 bg-slate-900/40 px-5 py-4"
            >
              <p className="text-base leading-relaxed tracking-wide text-slate-100">{line.text}</p>
            </motion.div>
          ))}

          {partial && (
            <div className="rounded-2xl border border-indigo-400/20 bg-indigo-500/10 px-5 py-4">
              <p className="mb-1 text-xs uppercase tracking-widest text-indigo-300">识别中</p>
              <p className="text-base leading-relaxed tracking-wide text-indigo-100">{partial}</p>
            </div>
          )}
        </div>
      </GlassCard>
    </motion.div>
  );
}
