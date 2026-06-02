'use client';

import { useMemo, useRef, useEffect } from 'react';
import dynamicImport from 'next/dynamic';
import { motion } from 'framer-motion';
import { MessageCircle } from 'lucide-react';
import { AmbientBackground } from '@/components/layout/AmbientBackground';
import { CursorGlow } from '@/components/layout/CursorGlow';
import { NavBar } from '@/components/layout/NavBar';
import { ChatConfigPanel } from '@/components/features/chat/ChatConfigPanel';
import { ChatInput } from '@/components/features/chat/ChatInput';
import { ChatMessageList } from '@/components/features/chat/ChatMessageList';
import { staggerContainer } from '@/components/ui/motion-presets';
import type { Live2DModelHandle } from '@/components/features/live2d/Live2DModel';
import { useAsrStream } from '@/hooks/useAsrStream';
import { useChat } from '@/hooks/useChat';

const Live2DModel = dynamicImport(
  () => import('@/components/features/live2d/Live2DModel'),
  { ssr: false }
);

export const dynamic = 'force-dynamic';

export default function ChatPage() {
  const {
    messages,
    llmConfig,
    loading,
    streaming: chatStreaming,
    speaking,
    autoSpeak,
    setAutoSpeak,
    ttsSpeakMode,
    setTtsSpeakMode,
    error,
    savingConfig,
    sendMessage,
    speakText,
    clearMessages,
    updateLlmConfig,
  } = useChat();

  const {
    streaming,
    starting: asrStarting,
    partial,
    inputText: asrInputText,
    start: asrStart,
    stop: asrStop,
  } = useAsrStream({ forChat: true });

  const live2dRef = useRef<Live2DModelHandle>(null);
  const lipTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const lastAssistantText = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i]?.role === 'assistant') return messages[i]?.content;
    }
    return undefined;
  }, [messages]);

  // Lip-sync: oscillate mouth when TTS is speaking
  useEffect(() => {
    if (speaking) {
      let t = 0;
      lipTimerRef.current = setInterval(() => {
        t += 0.1;
        // Simulate mouth movement with a combination of sine waves
        const v = 0.3 + 0.7 * Math.abs(Math.sin(t * 3) * Math.sin(t * 5.7));
        live2dRef.current?.setLipSync(v);
      }, 50);
    } else {
      if (lipTimerRef.current) {
        clearInterval(lipTimerRef.current);
        lipTimerRef.current = null;
      }
      live2dRef.current?.setLipSync(0);
    }
    return () => {
      if (lipTimerRef.current) {
        clearInterval(lipTimerRef.current);
        lipTimerRef.current = null;
      }
    };
  }, [speaking]);

  // Expression: show 笑嘻 when reflecting, default otherwise
  useEffect(() => {
    if (!live2dRef.current) return;
    if (chatStreaming || loading) {
      live2dRef.current.setExpression('我也要死吗');
    }
  }, [chatStreaming, loading]);

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
          <h1 className="flex items-center gap-3 text-4xl font-bold tracking-headline text-white md:text-5xl">
            <MessageCircle className="h-10 w-10 text-indigo-300" />
            语音对话
          </h1>
          <p className="mt-3 max-w-2xl text-sm tracking-wide text-slate-400 md:text-base">
            文字逐字显示；可选分句朗读（首句更快）或整段朗读（更连贯）。保存提示词后下一条消息即生效。TTS 音色请在 TTS 页配置。
          </p>
        </motion.div>

        {error && (
          <div className="mb-6 rounded-2xl border border-red-400/30 bg-red-500/10 px-5 py-4 text-sm tracking-wide text-red-200">
            {error}
          </div>
        )}

        <div className="flex gap-8 items-start">
          {/* Chat area (left) */}
          <motion.div
            className="flex-1 min-w-0 grid grid-cols-12 gap-8"
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
          >
            <ChatConfigPanel config={llmConfig} saving={savingConfig} onSave={updateLlmConfig} />
            <ChatMessageList messages={messages} loading={loading} streaming={chatStreaming} />
            <ChatInput
              loading={loading || chatStreaming}
              speaking={speaking}
              streaming={streaming}
              asrPartial={partial}
              asrInputText={asrInputText}
              asrStarting={asrStarting}
              autoSpeak={autoSpeak}
              onAutoSpeakChange={setAutoSpeak}
              ttsSpeakMode={ttsSpeakMode}
              onTtsSpeakModeChange={setTtsSpeakMode}
              onSend={sendMessage}
              onSpeakLast={speakText}
              onAsrStart={asrStart}
              onAsrStop={asrStop}
              lastAssistantText={lastAssistantText}
            />

            {messages.length > 0 && (
              <div className="col-span-12 mt-4 text-center">
                <button
                  type="button"
                  onClick={clearMessages}
                  className="text-xs tracking-wide text-slate-500 underline-offset-4 hover:text-slate-300 hover:underline"
                >
                  清空对话
                </button>
              </div>
            )}
          </motion.div>

          {/* Live2D character (right sidebar) */}
          <motion.div
            className="hidden xl:block shrink-0 w-[320px]"
            initial={{ opacity: 0, x: 30 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.8, delay: 0.3 }}
          >
            <div className="sticky top-32">
              <Live2DModel
                ref={live2dRef}
                modelPath="/live2d/models/14酱/"
                width={320}
                height={560}
                scale={0.85}
                yOffset={-0.05}
                onLoad={() => console.log('Live2D model loaded')}
                onError={(err) => console.error('Live2D error:', err)}
              />
            </div>
          </motion.div>
        </div>
      </main>
    </>
  );
}
