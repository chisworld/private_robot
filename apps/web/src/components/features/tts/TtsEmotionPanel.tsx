'use client';

import { useMemo } from 'react';
import { motion } from 'framer-motion';
import { Heart, Loader2, Plus, Save, Trash2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/GlassCard';
import { GlassInput } from '@/components/ui/GlassInput';
import { GlassSelect } from '@/components/ui/GlassSelect';
import { PathPickerField } from '@/components/ui/PathPickerField';
import { PrimaryButton } from '@/components/ui/PrimaryButton';
import { restoreVariants } from '@/components/ui/motion-presets';
import type { TtsDraft } from '@/hooks/useTtsDraft';
import { ttsApi } from '@/lib/api';

interface TtsEmotionPanelProps {
  draft: TtsDraft;
  saving: boolean;
  onPatch: <K extends keyof TtsDraft>(key: K, value: TtsDraft[K]) => void;
  onSelectEmotion: (id: string) => void;
  onUpdateLabel: (label: string) => void;
  onAdd: () => void;
  onRemove: () => void;
  onSave: () => Promise<void>;
}

export function TtsEmotionPanel({
  draft,
  saving,
  onPatch,
  onSelectEmotion,
  onUpdateLabel,
  onAdd,
  onRemove,
  onSave,
}: TtsEmotionPanelProps) {
  const activePreset = draft.emotion_presets.find((item) => item.id === draft.active_emotion_id);

  const previewSrc = useMemo(() => {
    const path = draft.ref_audio_path.trim();
    if (!path) return '';
    return ttsApi.referencePreviewUrl(path);
  }, [draft.ref_audio_path]);

  return (
    <motion.div variants={restoreVariants}>
      <GlassCard>
        <div className="mb-6 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Heart className="h-5 w-5 text-rose-300" />
            <h2 className="text-xl font-semibold tracking-headline text-white">情绪参考音</h2>
          </div>
          <div className="flex gap-2">
            <PrimaryButton
              variant="ghost"
              onClick={onAdd}
              disabled={saving}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs"
            >
              <Plus className="h-3.5 w-3.5" />
              添加
            </PrimaryButton>
            <PrimaryButton
              variant="ghost"
              onClick={onRemove}
              disabled={saving || draft.emotion_presets.length <= 1}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs"
            >
              <Trash2 className="h-3.5 w-3.5" />
              删除
            </PrimaryButton>
          </div>
        </div>

        {draft.emotion_presets.length === 0 ? (
          <PrimaryButton variant="ghost" onClick={onAdd} disabled={saving} className="w-full text-sm">
            创建第一条情绪预设
          </PrimaryButton>
        ) : (
          <div className="grid gap-5">
            <GlassSelect
              label="选择情绪"
              value={draft.active_emotion_id}
              disabled={saving}
              onChange={(e) => onSelectEmotion(e.target.value)}
              hint="合成时可临时切换；此处编辑各情绪的参考音频"
            >
              {draft.emotion_presets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label || item.id}
                </option>
              ))}
            </GlassSelect>

            <GlassInput
              label="情绪名称"
              value={activePreset?.label ?? ''}
              disabled={saving || !activePreset}
              onChange={(e) => onUpdateLabel(e.target.value)}
              placeholder="例如：平静 / 开心 / 生气"
            />

            <PathPickerField
              label="参考音频"
              value={draft.ref_audio_path}
              onChange={(path) => onPatch('ref_audio_path', path)}
              disabled={saving}
              mode="file"
              dialogTitle="选择参考音频"
              filetypes={[
                ['Audio', '*.wav *.mp3 *.flac *.ogg *.m4a'],
                ['All files', '*.*'],
              ]}
              hint="3–10 秒干声，情绪体现在这段录音里"
            />

            {previewSrc ? (
              <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-4">
                <p className="mb-3 text-xs uppercase tracking-widest text-slate-400">试听参考音频</p>
                <audio key={previewSrc} controls preload="metadata" src={previewSrc} className="w-full" />
              </div>
            ) : (
              <p className="rounded-2xl border border-dashed border-white/10 px-4 py-6 text-center text-xs text-slate-500">
                选择参考音频后可在此实时试听
              </p>
            )}

            <GlassInput
              label="参考音频文本"
              value={draft.prompt_text}
              disabled={saving}
              onChange={(e) => onPatch('prompt_text', e.target.value)}
              hint="必须与参考音频内容一致"
            />

            <PrimaryButton
              onClick={() => void onSave()}
              disabled={saving}
              className="inline-flex items-center gap-2"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              保存情绪配置
            </PrimaryButton>
          </div>
        )}
      </GlassCard>
    </motion.div>
  );
}
