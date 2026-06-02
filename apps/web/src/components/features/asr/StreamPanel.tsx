'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Loader2, Mic, Square, Upload } from 'lucide-react';
import { GlassCard } from '@/components/ui/GlassCard';
import { PrimaryButton } from '@/components/ui/PrimaryButton';
import { restoreVariants } from '@/components/ui/motion-presets';
import { VolumeMeter } from '@/components/features/asr/VolumeMeter';

interface StreamPanelProps {
  streaming: boolean;
  starting: boolean;
  status: string;
  audioLevel: number;
  activeThreshold: number;
  isSpeech: boolean;
  energyThreshold: number | null;
  onStart: () => void;
  onStop: () => void;
  onUpload: (file: File) => Promise<unknown>;
  onThresholdChange: (value: number | null) => Promise<unknown>;
}

const STATUS_LABEL: Record<string, string> = {
  idle: '待命',
  loading: '加载模型…',
  listening: '等待说话',
  speech: '正在聆听',
  stopped: '已停止',
  error: '出错',
};

const THRESHOLD_MIN = 0.005;
const THRESHOLD_MAX = 0.4;
const THRESHOLD_STEP = 0.005;

export function StreamPanel({
  streaming,
  starting,
  status,
  audioLevel,
  activeThreshold,
  isSpeech,
  energyThreshold,
  onStart,
  onStop,
  onUpload,
  onThresholdChange,
}: StreamPanelProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const busy = starting || status === 'loading';
  const manualThreshold = energyThreshold !== null;
  const [sliderValue, setSliderValue] = useState(energyThreshold ?? 0.03);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (energyThreshold !== null) {
      setSliderValue(energyThreshold);
    } else if (activeThreshold > 0) {
      setSliderValue(activeThreshold);
    }
  }, [energyThreshold, activeThreshold]);

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) await onUpload(file);
    e.target.value = '';
  };

  const applyThreshold = (value: number, manual: boolean) => {
    setSliderValue(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void onThresholdChange(manual ? value : null);
    }, 400);
  };

  return (
    <motion.div variants={restoreVariants}>
      <GlassCard className="flex h-full flex-col justify-between">
        <div>
          <div className="mb-6 flex items-center justify-between">
            <h2 className="text-xl font-semibold tracking-headline text-white">实时识别</h2>
            <span className="rounded-full border border-white/10 bg-slate-900/60 px-3 py-1 text-xs tracking-wide text-slate-300">
              {STATUS_LABEL[status] ?? status}
            </span>
          </div>

          <p className="mb-8 text-sm leading-relaxed tracking-wide text-slate-400">
            点击开始后对着麦克风说话，每句话说完停顿约 1 秒会输出结果。终端窗口可查看识别日志。
          </p>

          <div className="flex flex-wrap gap-4">
            {!streaming ? (
              <PrimaryButton
                onClick={onStart}
                disabled={busy}
                className="inline-flex items-center gap-2"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />}
                {busy ? '正在启动…' : '开始识别'}
              </PrimaryButton>
            ) : (
              <PrimaryButton
                variant="ghost"
                onClick={onStop}
                className="inline-flex items-center gap-2 border-red-400/30 text-red-200 hover:border-red-400/50"
              >
                <Square className="h-4 w-4" />
                停止
              </PrimaryButton>
            )}

            <PrimaryButton
              variant="ghost"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
              className="inline-flex items-center gap-2"
            >
              <Upload className="h-4 w-4" />
              上传音频
            </PrimaryButton>
            <input ref={fileRef} type="file" accept="audio/*" className="hidden" onChange={handleFile} />
          </div>
        </div>

        {(streaming || status === 'loading') && (
          <div className="mt-8 space-y-5">
            <div className="flex items-center gap-3">
              <span className="relative flex h-3 w-3 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-60" />
                <span className="relative inline-flex h-3 w-3 rounded-full bg-indigo-400" />
              </span>
              <span className="shrink-0 text-sm tracking-wide text-indigo-200">麦克风监听中</span>
              <VolumeMeter
                level={audioLevel}
                threshold={manualThreshold ? sliderValue : activeThreshold}
                isSpeech={isSpeech}
              />
            </div>

            <div className="rounded-2xl border border-white/10 bg-slate-900/40 px-4 py-4">
              <div className="mb-3 flex items-center justify-between">
                <span className="text-xs font-medium uppercase tracking-widest text-slate-400">
                  声音阈值
                </span>
                <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-400">
                  <input
                    type="checkbox"
                    checked={manualThreshold}
                    onChange={(e) => {
                      if (e.target.checked) {
                        applyThreshold(sliderValue, true);
                      } else {
                        void onThresholdChange(null);
                      }
                    }}
                    className="rounded border-white/20 bg-slate-800"
                  />
                  手动设置
                </label>
              </div>
              <input
                type="range"
                min={THRESHOLD_MIN}
                max={THRESHOLD_MAX}
                step={THRESHOLD_STEP}
                value={sliderValue}
                disabled={!manualThreshold}
                onChange={(e) => applyThreshold(Number(e.target.value), true)}
                className="h-2 w-full cursor-pointer appearance-none rounded-full bg-slate-700 accent-indigo-400 disabled:opacity-40"
              />
              <div className="mt-2 flex justify-between text-[11px] tracking-wide text-slate-500">
                <span>灵敏（{THRESHOLD_MIN}）</span>
                <span className="text-slate-300">
                  {manualThreshold ? sliderValue.toFixed(3) : `自动 · ${activeThreshold.toFixed(3)}`}
                </span>
                <span>迟钝（{THRESHOLD_MAX}）</span>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed tracking-wide text-slate-500">
                音量条超过白色竖线即触发识别。没反应就调低阈值，误触发就调高。
              </p>
            </div>
          </div>
        )}
      </GlassCard>
    </motion.div>
  );
}
