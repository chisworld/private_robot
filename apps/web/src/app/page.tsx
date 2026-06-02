'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { AmbientBackground } from '@/components/layout/AmbientBackground';
import { CursorGlow } from '@/components/layout/CursorGlow';
import { NavBar } from '@/components/layout/NavBar';
import { ModelPanel } from '@/components/features/asr/ModelPanel';
import { StreamPanel } from '@/components/features/asr/StreamPanel';
import { TranscriptPanel } from '@/components/features/asr/TranscriptPanel';
import { staggerContainer } from '@/components/ui/motion-presets';
import { asrApi, type LanguageOption } from '@/lib/api';
import { useAsrStream } from '@/hooks/useAsrStream';

export default function HomePage() {
  const {
    config,
    streaming,
    starting,
    status,
    partial,
    lines,
    error,
    saving,
    audioLevel,
    activeThreshold,
    isSpeech,
    updateConfig,
    updateThreshold,
    start,
    stop,
    transcribeFile,
    clearLines,
  } = useAsrStream();

  const [models, setModels] = useState<string[]>([]);
  const [languages, setLanguages] = useState<LanguageOption[]>([]);

  useEffect(() => {
    asrApi.getModels().then((data) => {
      setModels(data.models);
      setLanguages(data.languages);
    });
  }, []);

  return (
    <>
      <AmbientBackground />
      <CursorGlow />
      <NavBar />

      <main className="relative z-10 mx-auto max-w-7xl px-6 pb-16 pt-32">
        <motion.div
          className="mb-10"
          initial={{ opacity: 0, y: 20, filter: 'blur(12px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          transition={{ duration: 0.6 }}
        >
          <h1 className="text-4xl font-bold tracking-headline text-white md:text-5xl">
            语音转文字
          </h1>
          <p className="mt-3 max-w-2xl text-sm tracking-wide text-slate-400 md:text-base">
            Obsidian Glass 风格的本地语音识别台。支持切换 Whisper 模型、实时麦克风流式识别与音频文件上传。
          </p>
        </motion.div>

        {error && (
          <div className="mb-6 rounded-2xl border border-red-400/30 bg-red-500/10 px-5 py-4 text-sm tracking-wide text-red-200">
            {error}
          </div>
        )}

        {config?.model_warning && !error && (
          <div className="mb-6 rounded-2xl border border-amber-400/30 bg-amber-500/10 px-5 py-4 text-sm tracking-wide text-amber-100">
            {config.model_warning}
          </div>
        )}

        <motion.div
          className="grid grid-cols-12 gap-8"
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
        >
          <div className="col-span-12 space-y-8 lg:col-span-4">
            <ModelPanel
              config={config}
              models={models}
              languages={languages}
              saving={saving}
              streaming={streaming}
              onChange={updateConfig}
            />
            <StreamPanel
              streaming={streaming}
              starting={starting}
              status={status}
              audioLevel={audioLevel}
              activeThreshold={activeThreshold}
              isSpeech={isSpeech}
              energyThreshold={config?.energy_threshold ?? null}
              onStart={start}
              onStop={stop}
              onUpload={transcribeFile}
              onThresholdChange={updateThreshold}
            />
          </div>

          <TranscriptPanel lines={lines} partial={partial} onClear={clearLines} />
        </motion.div>
      </main>
    </>
  );
}
