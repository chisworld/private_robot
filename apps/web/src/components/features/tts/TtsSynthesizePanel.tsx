'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Loader2, Volume2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/GlassCard';
import { GlassSelect } from '@/components/ui/GlassSelect';
import { GlassTextarea } from '@/components/ui/GlassInput';
import { PrimaryButton } from '@/components/ui/PrimaryButton';
import { restoreVariants } from '@/components/ui/motion-presets';
import type { EmotionPreset } from '@/lib/api';

interface TtsSynthesizePanelProps {
  synthesizing: boolean;
  serverAlive: boolean;
  emotionPresets: EmotionPreset[];
  activeEmotionId: string;
  onSynthesize: (text: string, emotionId?: string) => Promise<unknown>;
}

export function TtsSynthesizePanel({
  synthesizing,
  serverAlive,
  emotionPresets,
  activeEmotionId,
  onSynthesize,
}: TtsSynthesizePanelProps) {
  const [text, setText] = useState('你好，我是 PNN Garden 语音助手。');
  const [emotionId, setEmotionId] = useState(activeEmotionId);

  useEffect(() => {
    setEmotionId(activeEmotionId);
  }, [activeEmotionId]);

  return (
    <motion.div variants={restoreVariants}>
      <GlassCard>
        <div className="mb-6 flex items-center gap-3">
          <Volume2 className="h-5 w-5 text-emerald-300" />
          <h2 className="text-xl font-semibold tracking-headline text-white">文字转语音</h2>
        </div>

        <div className="grid gap-6">
          {emotionPresets.length > 0 && (
            <GlassSelect
              label="合成情绪"
              value={emotionId}
              disabled={synthesizing}
              onChange={(e) => setEmotionId(e.target.value)}
              hint="临时切换语气，无需重新保存配置"
            >
              {emotionPresets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label || item.id}
                </option>
              ))}
            </GlassSelect>
          )}

          <GlassTextarea
            label="合成文本"
            value={text}
            disabled={synthesizing}
            onChange={(e) => setText(e.target.value)}
            placeholder="输入要朗读的文字…"
          />

          {!serverAlive && (
            <p className="rounded-2xl border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-xs tracking-wide text-amber-200">
              GPT-SoVITS 服务未连接。请先填写整合包路径并点击「启动服务」，或手动运行 api_v2.py。
            </p>
          )}

          <PrimaryButton
            onClick={() => void onSynthesize(text, emotionId === 'default' || !emotionId ? undefined : emotionId)}
            disabled={synthesizing || !text.trim()}
            className="inline-flex items-center gap-2"
          >
            {synthesizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Volume2 className="h-4 w-4" />}
            {synthesizing ? '合成中…' : '开始合成'}
          </PrimaryButton>
        </div>
      </GlassCard>
    </motion.div>
  );
}
