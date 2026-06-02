'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MessageCircle, Mic, Volume2 } from 'lucide-react';
import { cn } from '@/lib/cn';

import { getApiBase } from '@/lib/api';

interface NavBarProps {
  online?: boolean;
}

export function NavBar({ online: onlineProp }: NavBarProps) {
  const pathname = usePathname();
  const isAsr = pathname === '/';
  const isTts = pathname === '/tts';
  const isChat = pathname === '/chat';

  return (
    <header className="fixed left-1/2 top-6 z-30 w-[92%] max-w-7xl -translate-x-1/2">
      <nav className="flex items-center justify-between rounded-glass border border-white/10 bg-slate-900/40 px-8 py-4 backdrop-blur-3xl">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 mix-blend-screen">
            {isChat ? (
              <MessageCircle className="h-5 w-5 text-white" />
            ) : isTts ? (
              <Volume2 className="h-5 w-5 text-white" />
            ) : (
              <Mic className="h-5 w-5 text-white" />
            )}
          </div>
          <div>
            <p
              className="bg-gradient-to-r from-white via-indigo-200 to-purple-200 bg-clip-text text-lg font-semibold tracking-headline text-transparent"
              style={{ mixBlendMode: 'screen' }}
            >
              PNN Garden
            </p>
            <p className="text-xs tracking-wide text-slate-400">
              {isChat
                ? 'DeepSeek 对话 + TTS'
                : isTts
                  ? 'GPT-SoVITS 语音合成'
                  : 'faster-whisper 语音识别'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="flex items-center gap-1 rounded-2xl border border-white/10 bg-slate-900/50 p-1">
            <Link
              href="/"
              className={cn(
                'rounded-xl px-4 py-2 text-xs font-medium tracking-wide transition-all duration-300',
                isAsr ? 'bg-indigo-500/30 text-indigo-100' : 'text-slate-400 hover:text-slate-200',
              )}
            >
              ASR
            </Link>
            <Link
              href="/tts"
              className={cn(
                'rounded-xl px-4 py-2 text-xs font-medium tracking-wide transition-all duration-300',
                isTts ? 'bg-purple-500/30 text-purple-100' : 'text-slate-400 hover:text-slate-200',
              )}
            >
              TTS
            </Link>
            <Link
              href="/chat"
              className={cn(
                'rounded-xl px-4 py-2 text-xs font-medium tracking-wide transition-all duration-300',
                isChat ? 'bg-emerald-500/30 text-emerald-100' : 'text-slate-400 hover:text-slate-200',
              )}
            >
              对话
            </Link>
          </div>

          <NavStatus online={onlineProp} />
        </div>
      </nav>
    </header>
  );
}

function NavStatus({ online }: { online?: boolean }) {
  if (online === undefined) {
    return <NavStatusFetcher />;
  }
  return <StatusDot online={online} />;
}

function NavStatusFetcher() {
  const [online, setOnline] = useState(false);
  useEffect(() => {
    fetch(`${getApiBase()}/api/health`)
      .then((r) => r.ok && setOnline(true))
      .catch(() => setOnline(false));
  }, []);
  return <StatusDot online={online} />;
}

function StatusDot({ online }: { online: boolean }) {
  return (
    <div className="flex items-center gap-2 text-xs tracking-wide text-slate-400">
      <span className={`h-2 w-2 rounded-full ${online ? 'bg-emerald-400 animate-pulse-glow' : 'bg-red-400'}`} />
      {online ? '网关已连接' : '网关未连接'}
    </div>
  );
}
