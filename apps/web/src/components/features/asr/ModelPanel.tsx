'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Cpu, FolderOpen, Loader2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/GlassCard';
import { GlassSelect } from '@/components/ui/GlassSelect';
import { PrimaryButton } from '@/components/ui/PrimaryButton';
import { restoreVariants } from '@/components/ui/motion-presets';
import { ModelDownloadLinks } from '@/components/features/models/ModelDownloadLinks';
import type { AsrConfig, LanguageOption } from '@/lib/api';

interface ModelPanelProps {
  config: AsrConfig | null;
  models: string[];
  languages: LanguageOption[];
  saving: boolean;
  streaming: boolean;
  onChange: (patch: Partial<AsrConfig>) => Promise<unknown>;
}

export function ModelPanel({
  config,
  models,
  languages,
  saving,
  streaming,
  onChange,
}: ModelPanelProps) {
  const [localPath, setLocalPath] = useState(config?.model_path ?? '');

  useEffect(() => {
    setLocalPath(config?.model_path ?? '');
  }, [config?.model_path]);

  const applyLocalPath = () => {
    void onChange({ model_path: localPath.trim() || null });
  };

  return (
    <motion.div variants={restoreVariants}>
      <GlassCard>
        <div className="mb-6 flex items-center gap-3">
          <Cpu className="h-5 w-5 text-indigo-300" />
          <h2 className="text-xl font-semibold tracking-headline text-white">模型与引擎</h2>
        </div>

        <div className="grid gap-6">
          {config?.model_warning && (
            <p className="rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-xs leading-relaxed tracking-wide text-amber-100">
              {config.model_warning}
            </p>
          )}

          <GlassSelect
            label="Whisper 模型"
            value={config?.model ?? 'tiny'}
            disabled={streaming || saving}
            onChange={(e) => void onChange({ model: e.target.value })}
          >
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </GlassSelect>

          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium uppercase tracking-widest text-slate-400">
              本地模型路径（可选）
            </span>
            <div className="flex gap-2">
              <input
                value={localPath}
                onChange={(e) => setLocalPath(e.target.value)}
                disabled={streaming || saving}
                placeholder="D:\Project\pnn_garden\data\models\whisper\faster_whisper_tiny"
                className="min-w-0 flex-1 rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3 text-sm tracking-wide text-slate-100 outline-none transition-all duration-300 focus:border-indigo-400/60 focus:shadow-[0_0_0_3px_rgba(99,102,241,0.25)] disabled:opacity-50"
              />
              <PrimaryButton
                variant="ghost"
                onClick={applyLocalPath}
                disabled={streaming || saving}
                className="shrink-0 px-4"
              >
                <FolderOpen className="h-4 w-4" />
              </PrimaryButton>
            </div>
            <p className="text-xs tracking-wide text-slate-500">
              识别中文需多语言模型（Systran/faster-whisper-small，非 .en 版）
            </p>
          </div>

          <ModelDownloadLinks
            category="asr"
            title="Whisper 模型下载"
            hint="下载后解压到 models/ASR/whisper/ 对应子目录。"
          />

          <GlassSelect
            label="推理设备"
            value={config?.device ?? 'cuda'}
            disabled={streaming || saving}
            onChange={(e) => void onChange({ device: e.target.value })}
          >
            <option value="auto">自动检测</option>
            <option value="cpu">CPU</option>
            <option value="cuda">CUDA (GPU)</option>
          </GlassSelect>

          <GlassSelect
            label="识别语言"
            value={config?.language ?? ''}
            disabled={streaming || saving}
            onChange={(e) => void onChange({ language: e.target.value || null })}
          >
            {languages.map((lang) => (
              <option key={lang.code || 'auto'} value={lang.code}>
                {lang.label}
              </option>
            ))}
          </GlassSelect>

          {config?.resolved_device && (
            <p className="text-xs tracking-wide text-slate-400">
              当前运行设备：<span className="text-indigo-300">{config.resolved_device}</span>
            </p>
          )}

          {streaming && (
            <p className="rounded-2xl border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-xs tracking-wide text-amber-200">
              识别进行中，请先停止再更换模型
            </p>
          )}

          {(saving || config?.loading) && (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载模型…
            </div>
          )}
        </div>
      </GlassCard>
    </motion.div>
  );
}
