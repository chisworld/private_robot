import type { TtsSpeakMode } from '@/lib/api';

const TTS_SPEAK_MODE_KEY = 'pnn_chat_tts_speak_mode';

export function readTtsSpeakMode(): TtsSpeakMode {
  if (typeof window === 'undefined') return 'sentence';
  const raw = localStorage.getItem(TTS_SPEAK_MODE_KEY);
  return raw === 'full' ? 'full' : 'sentence';
}

export function writeTtsSpeakMode(mode: TtsSpeakMode): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TTS_SPEAK_MODE_KEY, mode);
}
