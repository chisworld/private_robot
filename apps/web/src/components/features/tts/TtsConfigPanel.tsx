'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Loader2, Server, Settings2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/GlassCard';
import { GlassInput } from '@/components/ui/GlassInput';
import { GlassSelect } from '@/components/ui/GlassSelect';
import { PathPickerField } from '@/components/ui/PathPickerField';
import { PrimaryButton } from '@/components/ui/PrimaryButton';
import { restoreVariants } from '@/components/ui/motion-presets';
import { ModelDownloadLinks } from '@/components/features/models/ModelDownloadLinks';
import type { TtsDraft } from '@/hooks/useTtsDraft';
import type { LanguageOption, TtsProviderOption } from '@/lib/api';
import { ttsApi } from '@/lib/api';

const DEFAULT_PROVIDERS: TtsProviderOption[] = [
  { id: 'gpt-sovits', label: 'GPT-SoVITS' },
  { id: 'genie-tts', label: 'Genie TTS' },
  { id: 'index-tts', label: 'Index TTS' },
  { id: 'cosyvoice', label: 'CosyVoice (阿里云)' },
];

interface TtsConfigPanelProps {
  draft: TtsDraft;
  serverAlive: boolean;
  languages: LanguageOption[];
  saving: boolean;
  starting: boolean;
  onPatch: <K extends keyof TtsDraft>(key: K, value: TtsDraft[K]) => void;
  onSave: () => Promise<void>;
  onSaveAndStart: () => Promise<void>;
}

export function TtsConfigPanel({
  draft,
  serverAlive,
  languages,
  saving,
  starting,
  onPatch,
  onSave,
  onSaveAndStart,
}: TtsConfigPanelProps) {
  const [providers, setProviders] = useState<TtsProviderOption[]>(DEFAULT_PROVIDERS);

  useEffect(() => {
    ttsApi
      .getProviders()
      .then((data) => setProviders(data.providers.length ? data.providers : DEFAULT_PROVIDERS))
      .catch(() => setProviders(DEFAULT_PROVIDERS));
  }, []);

  const provider = draft.provider;
  const isCloud = provider === 'cosyvoice';
  const isGenie = provider === 'genie-tts';

  return (
    <motion.div variants={restoreVariants}>
      <GlassCard>
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Settings2 className="h-5 w-5 text-purple-300" />
            <h2 className="text-xl font-semibold tracking-headline text-white">TTS 配置</h2>
          </div>
          <span
            className={`rounded-full border px-3 py-1 text-xs tracking-wide ${
              serverAlive
                ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
                : 'border-red-400/30 bg-red-400/10 text-red-200'
            }`}
          >
            {isCloud ? '云端 API' : serverAlive ? '服务在线' : '服务离线'}
          </span>
        </div>

        <div className="grid gap-5">
          <GlassSelect
            label="TTS 引擎"
            value={draft.provider}
            disabled={saving}
            onChange={(e) => onPatch('provider', e.target.value)}
          >
            {providers.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </GlassSelect>

          {isCloud ? (
            <GlassInput
              label="DashScope API Key"
              type="password"
              value={draft.api_key}
              disabled={saving}
              onChange={(e) => onPatch('api_key', e.target.value)}
              placeholder="sk-..."
            />
          ) : (
            <>
              <GlassInput
                label="API 地址"
                value={draft.server_url}
                disabled={saving}
                onChange={(e) => onPatch('server_url', e.target.value)}
                placeholder="http://127.0.0.1:9880"
              />

              <PathPickerField
                label="整合包 / 工作目录"
                value={draft.work_path}
                onChange={(path) => onPatch('work_path', path)}
                disabled={saving}
                mode="folder"
                dialogTitle="选择 GPT-SoVITS 整合包目录"
                placeholder="D:\Project\pnn_garden\models\TTS\GPT-SoVITS-v2pro-20250604"
                hint="含 runtime/python.exe 与 api_v2.py"
              />
            </>
          )}

          {!isCloud && !isGenie && (
            <>
              <PathPickerField
                label="GPT 模型 (.ckpt)"
                value={draft.gpt_model_path}
                onChange={(path) => onPatch('gpt_model_path', path)}
                disabled={saving}
                mode="file"
                dialogTitle="选择 GPT 模型"
                filetypes={[
                  ['GPT checkpoint', '*.ckpt'],
                  ['All files', '*.*'],
                ]}
              />

              <PathPickerField
                label="SoVITS 模型 (.pth)"
                value={draft.sovits_model_path}
                onChange={(path) => onPatch('sovits_model_path', path)}
                disabled={saving}
                mode="file"
                dialogTitle="选择 SoVITS 模型"
                filetypes={[
                  ['SoVITS weights', '*.pth'],
                  ['All files', '*.*'],
                ]}
              />
            </>
          )}

          {isGenie && (
            <>
              <GlassInput
                label="角色名"
                value={draft.character_name}
                disabled={saving}
                onChange={(e) => onPatch('character_name', e.target.value)}
              />
              <PathPickerField
                label="ONNX 模型目录"
                value={draft.onnx_model_dir}
                onChange={(path) => onPatch('onnx_model_dir', path)}
                disabled={saving}
                mode="folder"
                dialogTitle="选择 ONNX 模型目录"
              />
              <PathPickerField
                label="GPT 模型 (.ckpt，可选)"
                value={draft.gpt_model_path}
                onChange={(path) => onPatch('gpt_model_path', path)}
                disabled={saving}
                mode="file"
                dialogTitle="选择 GPT 模型"
                filetypes={[['GPT checkpoint', '*.ckpt'], ['All files', '*.*']]}
              />
              <PathPickerField
                label="SoVITS 模型 (.pth，可选)"
                value={draft.sovits_model_path}
                onChange={(path) => onPatch('sovits_model_path', path)}
                disabled={saving}
                mode="file"
                dialogTitle="选择 SoVITS 模型"
                filetypes={[['SoVITS weights', '*.pth'], ['All files', '*.*']]}
              />
            </>
          )}

          <div className="grid gap-5 sm:grid-cols-2">
            <GlassSelect
              label="参考语言"
              value={draft.prompt_lang}
              disabled={saving}
              onChange={(e) => onPatch('prompt_lang', e.target.value)}
            >
              {languages.map((lang) => (
                <option key={lang.code} value={lang.code}>
                  {lang.label}
                </option>
              ))}
            </GlassSelect>

            <GlassSelect
              label="合成语言"
              value={draft.text_lang}
              disabled={saving}
              onChange={(e) => onPatch('text_lang', e.target.value)}
            >
              {languages.map((lang) => (
                <option key={`text-${lang.code}`} value={lang.code}>
                  {lang.label}
                </option>
              ))}
            </GlassSelect>
          </div>

          <GlassInput
            label="语速"
            type="number"
            min={0.5}
            max={2}
            step={0.1}
            value={draft.speed_factor}
            disabled={saving}
            onChange={(e) => onPatch('speed_factor', Number(e.target.value))}
          />

          {!isCloud && (
            <label className="flex items-center gap-3 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={draft.auto_start_server}
                disabled={saving}
                onChange={(e) => onPatch('auto_start_server', e.target.checked)}
                className="rounded border-white/20 bg-white/5"
              />
              自动启动本地 TTS 服务
            </label>
          )}

          {!isCloud && provider === 'gpt-sovits' && (
            <ModelDownloadLinks
              category="tts"
              title="TTS 模型下载"
              hint="整合包与角色权重需提前下载到本地。"
            />
          )}

          <div className="flex flex-wrap gap-3">
            <PrimaryButton onClick={() => void onSave()} disabled={saving} className="inline-flex items-center gap-2">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              保存配置
            </PrimaryButton>
            {!isCloud && (
              <PrimaryButton
                variant="ghost"
                onClick={() => void onSaveAndStart()}
                disabled={starting || saving}
                className="inline-flex items-center gap-2"
              >
                {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Server className="h-4 w-4" />}
                保存并启动服务
              </PrimaryButton>
            )}
          </div>
        </div>
      </GlassCard>
    </motion.div>
  );
}
