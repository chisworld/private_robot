'use client';

import { useCallback } from 'react';
import { motion } from 'framer-motion';
import { AmbientBackground } from '@/components/layout/AmbientBackground';
import { CursorGlow } from '@/components/layout/CursorGlow';
import { NavBar } from '@/components/layout/NavBar';
import { TtsConfigPanel } from '@/components/features/tts/TtsConfigPanel';
import { TtsEmotionPanel } from '@/components/features/tts/TtsEmotionPanel';
import { TtsPlayerPanel } from '@/components/features/tts/TtsPlayerPanel';
import { TtsSynthesizePanel } from '@/components/features/tts/TtsSynthesizePanel';
import { staggerContainer } from '@/components/ui/motion-presets';
import { useTtsDraft } from '@/hooks/useTtsDraft';
import { useTts } from '@/hooks/useTts';

export default function TtsPage() {
  const {
    config,
    serverAlive,
    languages,
    saving,
    starting,
    synthesizing,
    error,
    audioUrl,
    lastText,
    updateConfig,
    startServer,
    synthesize,
    clearAudio,
  } = useTts();

  const {
    draft,
    patchDraft,
    selectEmotion,
    updateActiveLabel,
    addEmotion,
    removeActiveEmotion,
    saveDraft,
  } = useTtsDraft(config, updateConfig);

  const saveAndStart = useCallback(async () => {
    await saveDraft();
    await startServer();
  }, [saveDraft, startServer]);

  const isCloud = draft.provider === 'cosyvoice';

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
          <h1 className="text-4xl font-bold tracking-headline text-white md:text-5xl">文字转语音</h1>
          <p className="mt-3 max-w-2xl text-sm tracking-wide text-slate-400 md:text-base">
            与 AI_assistant 相同的 TTS 引擎（GPT-SoVITS / Genie TTS 等）。左侧配置模型，右侧管理情绪参考音并试听。
          </p>
        </motion.div>

        {error && (
          <div className="mb-6 rounded-2xl border border-red-400/30 bg-red-500/10 px-5 py-4 text-sm tracking-wide text-red-200">
            {error}
          </div>
        )}

        <motion.div
          className="grid grid-cols-12 gap-8"
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
        >
          <div className="col-span-12 space-y-8 lg:col-span-4">
            <TtsConfigPanel
              draft={draft}
              serverAlive={serverAlive}
              languages={languages}
              saving={saving}
              starting={starting}
              onPatch={patchDraft}
              onSave={saveDraft}
              onSaveAndStart={saveAndStart}
            />
            <TtsSynthesizePanel
              synthesizing={synthesizing}
              serverAlive={serverAlive}
              emotionPresets={draft.emotion_presets}
              activeEmotionId={draft.active_emotion_id}
              onSynthesize={synthesize}
            />
          </div>

          <div className="col-span-12 space-y-8 lg:col-span-8">
            {!isCloud && (
              <TtsEmotionPanel
                draft={draft}
                saving={saving}
                onPatch={patchDraft}
                onSelectEmotion={selectEmotion}
                onUpdateLabel={updateActiveLabel}
                onAdd={addEmotion}
                onRemove={removeActiveEmotion}
                onSave={saveDraft}
              />
            )}
            <TtsPlayerPanel audioUrl={audioUrl} lastText={lastText} onClear={clearAudio} />
          </div>
        </motion.div>
      </main>
    </>
  );
}
