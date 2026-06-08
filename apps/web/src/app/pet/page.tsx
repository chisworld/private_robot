'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import type { Live2DModelHandle } from '@/components/features/live2d/Live2DModel';
import dynamicImport from 'next/dynamic';
import {
  chatApi,
  ttsApi,
  asrApi,
  type LlmConfig,
  type TtsConfig,
  type AsrConfig,
  type CharacterSummary,
} from '@/lib/api';

const Live2DModel = dynamicImport(
  () => import('@/components/features/live2d/Live2DModel'),
  { ssr: false }
);

export const dynamic = 'force-dynamic';

// ── Emotion detection ───────────────────────────────────────────────────────────

const EMOTION_MAP: Record<string, string> = {
  happy: '默认',
  love: '脸红',
  angry: '默认',
  sad: '哭',
  shy: '脸红',
  confused: '默认',
  surprise: '默认',
  default: '默认',
};

function detectEmotion(text: string): string {
  const t = text.toLowerCase();
  if (/かわいい|好き|大好き|愛|嬉しい|楽しい|素敵|最高|笑|ありがとう|よかった/.test(t)) return 'happy';
  if (/愛して|大好き|キス|抱き/.test(t)) return 'love';
  if (/怒|ふざけ|ばか|最低|許|むかつく/.test(t)) return 'angry';
  if (/悲|泣|ごめん|つらい|寂しい|さようなら|別れ/.test(t)) return 'sad';
  if (/恥ずかしい|照れ|はじ|どきどき|胸|ドキドキ/.test(t)) return 'shy';
  if (/えっ|なに|なぜ|どうして|混乱|わからない|不思議/.test(t)) return 'confused';
  if (/まさか|嘘|本当|驚|びっくり/.test(t)) return 'surprise';
  return 'default';
}

function pickExpression(text: string): string {
  return EMOTION_MAP[detectEmotion(text)] || EMOTION_MAP.default;
}

// ── Posture names ──────────────────────────────────────────────────────────────

const POSTURE_LABELS: Record<string, string> = {
  stand: '站立',
  sit: '坐着',
  crouch: '蹲下',
};

// ── Settings Drawer ─────────────────────────────────────────────────────────────

function SettingsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<'llm' | 'tts' | 'asr'>('llm');
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null);
  const [_ttsConfig, setTtsConfig] = useState<TtsConfig | null>(null);
  const [_asrConfig, setAsrConfig] = useState<AsrConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [activeChar, setActiveChar] = useState('');
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
  const [ttsProvider, setTtsProvider] = useState('');
  const [ttsServerUrl, setTtsServerUrl] = useState('');
  const [ttsRefAudio, setTtsRefAudio] = useState('');
  const [ttsPromptText, setTtsPromptText] = useState('');
  const [ttsPromptLang, setTtsPromptLang] = useState('zh');
  const [ttsTextLang, setTtsTextLang] = useState('zh');
  const [ttsSpeed, setTtsSpeed] = useState(1.0);
  const [asrModel, setAsrModel] = useState('');
  const [asrLang, setAsrLang] = useState('zh');
  const [asrSilence, setAsrSilence] = useState(1.0);

  useEffect(() => {
    if (!open || loaded) return;
    setLoaded(true);
    chatApi.getConfig().then((c) => {
      setLlmConfig(c); setBaseUrl(c.base_url); setModel(c.model);
      setSystemPrompt(c.system_prompt ?? ''); setActiveChar(c.active_character ?? '');
      setCharacters(c.characters ?? []);
    }).catch(() => {});
    ttsApi.getConfig().then((c) => {
      setTtsConfig(c); setTtsProvider(c.provider); setTtsServerUrl(c.server_url);
      setTtsRefAudio(c.ref_audio_path); setTtsPromptText(c.prompt_text);
      setTtsPromptLang(c.prompt_lang); setTtsTextLang(c.text_lang); setTtsSpeed(c.speed_factor);
    }).catch(() => {});
    asrApi.getConfig().then((c) => {
      setAsrConfig(c); setAsrModel(c.model); setAsrLang(c.language ?? 'zh');
      setAsrSilence(c.silence_duration);
    }).catch(() => {});
  }, [open, loaded]);

  const tabBtn = (t: typeof tab): React.CSSProperties => ({
    flex: 1, textAlign: 'center', padding: '8px 0', fontSize: 11, cursor: 'pointer',
    color: tab === t ? '#e2e8f0' : '#64748b', background: tab === t ? 'rgba(99,102,241,0.15)' : 'transparent',
    border: 'none', borderRadius: 6, fontWeight: tab === t ? 600 : 400,
  });

  const inp: React.CSSProperties = {
    width: '100%', height: 28, padding: '0 8px', borderRadius: 6,
    border: '1px solid rgba(148,163,184,0.2)', background: 'rgba(15,23,42,0.5)',
    color: '#e2e8f0', fontSize: 11, outline: 'none', boxSizing: 'border-box',
  };
  const lbl: React.CSSProperties = { fontSize: 10, color: '#94a3b8', marginBottom: 2, display: 'block' };
  const btn = (bg: string): React.CSSProperties => ({
    height: 30, borderRadius: 6, border: 'none', background: bg, color: '#fff',
    fontSize: 11, cursor: 'pointer', marginTop: 4,
  });

  if (!open) return null;

  return (
    <div style={{
      position: 'absolute', top: 0, right: 0, bottom: 0, width: 280,
      background: 'rgba(15,23,42,0.96)', backdropFilter: 'blur(20px)',
      borderLeft: '1px solid rgba(148,163,184,0.12)', zIndex: 50,
      display: 'flex', flexDirection: 'column', boxShadow: '-4px 0 20px rgba(0,0,0,0.5)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px', borderBottom: '1px solid rgba(148,163,184,0.08)' }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>设置</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 16, padding: 0 }}>✕</button>
      </div>
      <div style={{ display: 'flex', padding: '6px 8px', gap: 4 }}>
        <button style={tabBtn('llm')} onClick={() => setTab('llm')}>LLM</button>
        <button style={tabBtn('tts')} onClick={() => setTab('tts')}>TTS</button>
        <button style={tabBtn('asr')} onClick={() => setTab('asr')}>ASR</button>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 10 }}>
        {tab === 'llm' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div><label style={lbl}>API Key</label><input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={llmConfig?.configured ? `已配置 ${llmConfig.api_key_masked}` : 'sk-…'} style={inp} /></div>
            <div><label style={lbl}>API 地址</label><input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} style={inp} /></div>
            <div><label style={lbl}>模型</label><input value={model} onChange={(e) => setModel(e.target.value)} style={inp} /></div>
            <div><label style={lbl}>角色</label><select value={activeChar} onChange={(e) => setActiveChar(e.target.value)} style={{ ...inp, height: 30 }}><option value="">（无）</option>{characters.map((c) => (<option key={c.id} value={c.id}>{c.name || c.id}</option>))}</select></div>
            <div><label style={lbl}>输出规则</label><textarea value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} style={{ ...inp, height: 60, resize: 'vertical', padding: '4px 8px' }} /></div>
            <button onClick={async () => { setSaving(true); try { await chatApi.updateConfig({ ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}), base_url: baseUrl.trim(), model: model.trim(), system_prompt: systemPrompt, active_character: activeChar }); setApiKey(''); } catch (e) { console.error(e); } setSaving(false); }} disabled={saving} style={btn('rgba(99,102,241,0.6)')}>{saving ? '保存中…' : '保存 LLM 配置'}</button>
          </div>
        )}
        {tab === 'tts' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div><label style={lbl}>引擎</label><select value={ttsProvider} onChange={(e) => setTtsProvider(e.target.value)} style={{ ...inp, height: 30 }}><option value="gpt-sovits">GPT-SoVITS</option><option value="genie-tts">Genie TTS</option><option value="cosyvoice">CosyVoice</option></select></div>
            <div><label style={lbl}>服务器</label><input value={ttsServerUrl} onChange={(e) => setTtsServerUrl(e.target.value)} style={inp} /></div>
            <div><label style={lbl}>参考音频</label><input value={ttsRefAudio} onChange={(e) => setTtsRefAudio(e.target.value)} style={inp} /></div>
            <div><label style={lbl}>提示文本</label><input value={ttsPromptText} onChange={(e) => setTtsPromptText(e.target.value)} style={inp} /></div>
            <div style={{ display: 'flex', gap: 8 }}>
              <div style={{ flex: 1 }}><label style={lbl}>提示语言</label><select value={ttsPromptLang} onChange={(e) => setTtsPromptLang(e.target.value)} style={{ ...inp, height: 30 }}><option value="zh">中文</option><option value="ja">日文</option><option value="en">英文</option></select></div>
              <div style={{ flex: 1 }}><label style={lbl}>合成语言</label><select value={ttsTextLang} onChange={(e) => setTtsTextLang(e.target.value)} style={{ ...inp, height: 30 }}><option value="zh">中文</option><option value="ja">日文</option><option value="en">英文</option></select></div>
            </div>
            <div><label style={lbl}>语速 ({ttsSpeed.toFixed(1)})</label><input type="range" min={0.5} max={2.0} step={0.1} value={ttsSpeed} onChange={(e) => setTtsSpeed(parseFloat(e.target.value))} style={{ width: '100%' }} /></div>
            <button onClick={async () => { setSaving(true); try { await ttsApi.updateConfig({ provider: ttsProvider, server_url: ttsServerUrl, ref_audio_path: ttsRefAudio, prompt_text: ttsPromptText, prompt_lang: ttsPromptLang, text_lang: ttsTextLang, speed_factor: ttsSpeed }); } catch (e) { console.error(e); } setSaving(false); }} disabled={saving} style={btn('rgba(168,85,247,0.6)')}>{saving ? '保存中…' : '保存 TTS 配置'}</button>
          </div>
        )}
        {tab === 'asr' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div><label style={lbl}>模型</label><input value={asrModel} onChange={(e) => setAsrModel(e.target.value)} style={inp} /></div>
            <div><label style={lbl}>语言</label><select value={asrLang} onChange={(e) => setAsrLang(e.target.value)} style={{ ...inp, height: 30 }}><option value="zh">中文</option><option value="ja">日文</option><option value="en">英文</option><option value="auto">自动检测</option></select></div>
            <div><label style={lbl}>静音检测 ({asrSilence.toFixed(1)}s)</label><input type="range" min={0.2} max={3.0} step={0.1} value={asrSilence} onChange={(e) => setAsrSilence(parseFloat(e.target.value))} style={{ width: '100%' }} /></div>
            <button onClick={async () => { setSaving(true); try { await asrApi.updateConfig({ model: asrModel, language: asrLang, silence_duration: asrSilence }); } catch (e) { console.error(e); } setSaving(false); }} disabled={saving} style={btn('rgba(34,211,238,0.6)')}>{saving ? '保存中…' : '保存 ASR 配置'}</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Posture / Motion Overlay ──────────────────────────────────────────────────

function PostureMotionOverlay({
  live2dRef,
  posture,
  setPosture,
  motionSpeed,
  setMotionSpeed,
  actionDuration,
  setActionDuration,
}: {
  live2dRef: React.RefObject<Live2DModelHandle | null>;
  posture: string;
  setPosture: (p: string) => void;
  motionSpeed: number;
  setMotionSpeed: (s: number) => void;
  actionDuration: number;
  setActionDuration: (d: number) => void;
}) {
  const handlePostureChange = useCallback((p: string) => {
    setPosture(p);
    live2dRef.current?.setPosture(p);
  }, [live2dRef, setPosture]);

  const handleMotionClick = useCallback(() => {
    live2dRef.current?.triggerTapReaction();
  }, [live2dRef]);

  const handleActionClick = useCallback(() => {
    live2dRef.current?.playAction();
  }, [live2dRef]);

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      padding: '4px 0',
    }}>
      {/* Posture buttons */}
      <div style={{ display: 'flex', gap: 2, background: 'rgba(15,23,42,0.3)', borderRadius: 6, padding: 1 }}>
        {Object.entries(POSTURE_LABELS).map(([key, label]) => (
          <button
            key={key}
            onClick={() => handlePostureChange(key)}
            style={{
              border: 'none',
              borderRadius: 5,
              padding: '2px 8px',
              fontSize: 9,
              cursor: 'pointer',
              background: posture === key ? 'rgba(99,102,241,0.4)' : 'transparent',
              color: posture === key ? '#e2e8f0' : '#64748b',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Motion buttons */}
      <button
        onClick={handleMotionClick}
        style={{
          border: 'none', borderRadius: 5, padding: '2px 8px', fontSize: 9,
          cursor: 'pointer', background: 'rgba(99,102,241,0.2)', color: '#a5b4fc',
        }}
      >▶ 动作</button>
      <button
        onClick={handleActionClick}
        style={{
          border: 'none', borderRadius: 5, padding: '2px 8px', fontSize: 9,
          cursor: 'pointer', background: 'rgba(168,85,247,0.25)', color: '#c4b5fd',
        }}
      >🎭 随机道具</button>

      {/* Speed slider */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginLeft: 4 }}>
        <span style={{ fontSize: 8, color: '#64748b' }}>速度</span>
        <input
          type="range"
          min={0.2}
          max={2.0}
          step={0.1}
          value={motionSpeed}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            setMotionSpeed(v);
            live2dRef.current?.setMotionSpeed(v);
          }}
          style={{ width: 50, height: 4 }}
        />
        <span style={{ fontSize: 8, color: '#94a3b8', width: 24 }}>{motionSpeed.toFixed(1)}x</span>
      </div>

      {/* Action duration */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
        <span style={{ fontSize: 8, color: '#64748b' }}>持续</span>
        <input
          type="range"
          min={1}
          max={15}
          step={1}
          value={actionDuration}
          onChange={(e) => {
            const v = parseInt(e.target.value, 10);
            setActionDuration(v);
            live2dRef.current?.setActionDuration(v);
          }}
          style={{ width: 40, height: 4 }}
        />
        <span style={{ fontSize: 8, color: '#94a3b8', width: 20 }}>{actionDuration}s</span>
      </div>
    </div>
  );
}

// ── Main Pet ────────────────────────────────────────────────────────────────────

export default function PetPage() {
  const live2dRef = useRef<Live2DModelHandle>(null);
  const [expression, setExpression] = useState('默认');
  const [inputText, setInputText] = useState('');
  const [reply, setReply] = useState('');
  const [loading, setLoading] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [listening, setListening] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [muteTts, setMuteTts] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showBubble, setShowBubble] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [ttsAvailable, setTtsAvailable] = useState(true);
  const [ttsReply, setTtsReply] = useState('');
  const [modelReady, setModelReady] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const [embedQt, setEmbedQt] = useState(true);
  // ── New state for posture and motion ──
  const [posture, setPostureState] = useState('stand');
  const [motionSpeed, setMotionSpeedState] = useState(1.0);
  const [actionDuration, setActionDuration] = useState(3);
  const historyRef = useRef<{ role: 'user' | 'assistant'; content: string }[]>([]);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    setEmbedQt(q.get('embed') === 'qt' || q.get('embed') === '1');
  }, []);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const lipTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const bubbleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listeningRef = useRef(false);
  const loadingRef = useRef(false);

  // Lip-sync
  useEffect(() => {
    if (speaking) {
      let t = 0;
      lipTimerRef.current = setInterval(() => {
        t += 0.1;
        live2dRef.current?.setLipSync(0.3 + 0.7 * Math.abs(Math.sin(t * 3) * Math.sin(t * 5.7)));
      }, 50);
    } else {
      if (lipTimerRef.current) { clearInterval(lipTimerRef.current); lipTimerRef.current = null; }
      live2dRef.current?.setLipSync(0);
    }
    return () => { if (lipTimerRef.current) clearInterval(lipTimerRef.current); };
  }, [speaking]);

  // Hover debounce
  const onMouseEnter = useCallback(() => {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    setHovered(true);
  }, []);
  const onMouseLeave = useCallback(() => {
    hoverTimerRef.current = setTimeout(() => {
      if (!settingsOpen) setHovered(false);
    }, 800);
  }, [settingsOpen]);

  // Close hover menu when settings close
  useEffect(() => {
    if (!settingsOpen && !hovered) {
      // If settings closed and mouse left, keep hidden
    }
  }, [settingsOpen, hovered]);

  // TTS playback — triggered only when final reply is ready (not on streaming)
  useEffect(() => {
    if (!ttsReply || muteTts || !ttsAvailable) return;
    let cancelled = false;
    const audio = new Audio();
    setSpeaking(true);
    ttsApi.synthesize(ttsReply).then((blob) => {
      if (cancelled) { setSpeaking(false); return; }
      const url = URL.createObjectURL(blob);
      audio.src = url;
      audio.onended = () => { URL.revokeObjectURL(url); if (!cancelled) setSpeaking(false); };
      audio.onerror = () => { URL.revokeObjectURL(url); if (!cancelled) setSpeaking(false); };
      audio.play().catch(() => { if (!cancelled) setSpeaking(false); });
    }).catch(() => {
      setTtsAvailable(false);
      const duration = Math.min(ttsReply.length * 0.12, 8) * 1000;
      setTimeout(() => { if (!cancelled) setSpeaking(false); }, duration);
    });
    return () => { cancelled = true; audio.pause(); };
  }, [ttsReply, muteTts, ttsAvailable]);

  // Auto-dismiss bubble
  const showReplyBubble = useCallback((text: string) => {
    setReply(text); setShowBubble(true);
    if (bubbleTimerRef.current) clearTimeout(bubbleTimerRef.current);
    bubbleTimerRef.current = setTimeout(() => setShowBubble(false), 10000);
  }, []);

  // Send message
  const sendMessage = useCallback(async (text?: string) => {
    const msg = (text ?? inputText).trim();
    if (!msg || loadingRef.current) return;
    setInputText(''); setLoading(true); loadingRef.current = true;
    // Clear bubble immediately — avoid flashing previous reply
    setReply(''); setShowBubble(false);

    historyRef.current.push({ role: 'user', content: msg });
    try {
      let full = '';
      for await (const delta of chatApi.streamComplete(msg, historyRef.current.slice(0, -1))) {
        full += delta;
        // Atomically set reply AND show the bubble in one render cycle
        setReply(full);
        if (!showBubble && full.length > 0) {
          setShowBubble(true);
        }
      }
      historyRef.current.push({ role: 'assistant', content: full });
      showReplyBubble(full);
      const expr = pickExpression(full);
      setExpression(expr);
      live2dRef.current?.setExpression(expr);
      // Trigger TTS with final reply only
      setTtsReply(full);
    } catch (err) {
      console.error('Chat error:', err);
      setReply('连接失败，请检查 API 配置');
      setShowBubble(true);
    } finally {
      setLoading(false);
      loadingRef.current = false;
    }
  }, [inputText, showReplyBubble]);

  // Stable sendMessage via ref
  const sendMessageRef = useRef(sendMessage);
  sendMessageRef.current = sendMessage;

  // Voice input — stable callback
  const toggleMic = useCallback(async () => {
    if (listeningRef.current) {
      mediaRecorderRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
      const recorder = new MediaRecorder(stream, { mimeType: mime });
      audioChunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        listeningRef.current = false;
        setListening(false);
        if (audioChunksRef.current.length === 0) return;
        setProcessing(true);
        try {
          const blob = new Blob(audioChunksRef.current, { type: mime });
          const result = await asrApi.transcribeFile(new File([blob], 'rec.webm', { type: mime }));
          if (result.text?.trim()) {
            setInputText(result.text.trim());
            setTimeout(() => sendMessageRef.current?.(result.text.trim()), 300);
          }
        } catch (err) { console.error('ASR error:', err); }
        finally { setProcessing(false); }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      listeningRef.current = true;
      setListening(true);
    } catch (err) { console.error('Mic error:', err); }
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  }, [sendMessage]);

  // Ctrl+M mic shortcut
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.ctrlKey && e.key === 'm') { e.preventDefault(); toggleMic(); } };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [toggleMic]);

  const transitioning =
    embedQt || hovered || settingsOpen || listening || processing || showBubble;

  const pageBg = embedQt
    ? 'radial-gradient(ellipse at 50% 80%, #1e293b 0%, #0f172a 70%)'
    : 'transparent';

  return (
    <div
      onMouseEnter={onMouseEnter}
      onMouseMove={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{
        width: '100vw', height: '100vh', background: pageBg,
        position: 'relative', overflow: 'hidden', userSelect: 'none',
        fontFamily: "'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif",
      }}
    >
      <style>{embedQt ? `
        html,body,#__next{margin:0;padding:0;min-height:100%;background:#0f172a!important}
        .bg-canvas{background-color:#0f172a!important}
        body::before,body::after{display:none!important}
      ` : `
        html,body,#__next,div[hidden]{background-color:transparent!important}
        html,body{margin:0;padding:0;background-size:cover;background-position:0 0}
        body::before,body::after{display:none!important}
        .bg-canvas{background-color:transparent!important}
      `}</style>

      {/* Drag area — top strip */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 40, zIndex: 5 }} />

      {/* Character */}
      <div
        style={{
          position: 'absolute', top: -20, left: 0, right: 0, bottom: -20,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          pointerEvents: 'none', zIndex: 1,
        }}
        onClick={(e) => {
          // Click on character → tap reaction
          e.stopPropagation();
          live2dRef.current?.triggerTapReaction();
        }}
      >
        <Live2DModel
          ref={live2dRef}
          modelPath="/live2d/models/吸血姬/"
          width={300}
          height={540}
          scale={0.75}
          yOffset={-0.05}
          activeExpression={expression}
          onLoad={() => {
            setModelReady(true);
            setModelError(null);
            // Apply initial posture after model loads
            setTimeout(() => live2dRef.current?.setPosture(posture), 200);
          }}
          onError={(err) => {
            setModelReady(false);
            setModelError(err.message);
          }}
        />
      </div>

      {!modelReady && !modelError && (
        <div style={{
          position: 'absolute', left: '50%', top: '45%', transform: 'translate(-50%,-50%)',
          color: '#94a3b8', fontSize: 12, zIndex: 10, pointerEvents: 'none',
        }}>
          加载角色中…
        </div>
      )}
      {modelError && (
        <>
          <img
            src="/live2d/models/14酱/我也要死吗.2048/texture_00.png"
            alt=""
            style={{
              position: 'absolute', left: '50%', top: '42%', transform: 'translate(-50%,-50%)',
              maxWidth: 220, maxHeight: 380, opacity: 0.35, zIndex: 2, pointerEvents: 'none',
            }}
          />
          <div style={{
            position: 'absolute', left: 10, right: 10, top: '8%',
            background: 'rgba(127,29,29,0.9)', color: '#fecaca', fontSize: 11,
            padding: '10px 12px', borderRadius: 8, zIndex: 30, lineHeight: 1.5,
            pointerEvents: 'auto',
          }}>
            角色加载失败：{modelError}
            <br />
            <span style={{ color: '#fca5a5' }}>
              请运行：python scripts/sync_live2d_assets.py
            </span>
          </div>
        </>
      )}

      {/* ── Hover UI overlay ── */}
      <div style={{
        position: 'absolute', inset: 0, zIndex: 20, pointerEvents: 'none',
        opacity: transitioning ? 1 : 0,
        transition: 'opacity 0.35s ease',
      }}>
        {/* Settings gear */}
        <button
          onClick={() => setSettingsOpen((v) => !v)}
          style={{
            position: 'absolute', top: 8, right: 8, width: 26, height: 26,
            borderRadius: '50%', border: 'none',
            background: settingsOpen ? 'rgba(99,102,241,0.35)' : 'rgba(15,23,42,0.25)',
            color: '#94a3b8', cursor: 'pointer', display: 'flex',
            alignItems: 'center', justifyContent: 'center', fontSize: 12,
            pointerEvents: 'auto', backdropFilter: 'blur(4px)',
          }}
        >⚙</button>

        {/* Mute */}
        <button
          onClick={() => setMuteTts((v) => !v)}
          style={{
            position: 'absolute', top: 8, right: 40, width: 26, height: 26,
            borderRadius: '50%', border: 'none',
            background: muteTts ? 'rgba(239,68,68,0.25)' : 'rgba(15,23,42,0.25)',
            color: '#94a3b8', cursor: 'pointer', display: 'flex',
            alignItems: 'center', justifyContent: 'center', fontSize: 11,
            pointerEvents: 'auto', backdropFilter: 'blur(4px)',
          }}
        >{muteTts ? '🔇' : '🔊'}</button>

        {/* Expression tag */}
        <div style={{
          position: 'absolute', top: 40, right: 8,
          background: 'rgba(99,102,241,0.12)', color: '#a5b4fc',
          fontSize: 9, padding: '1px 7px', borderRadius: 6,
          border: '1px solid rgba(129,140,248,0.12)',
        }}>{expression}</div>

        {/* ── Posture + motion controls ── */}
        <div style={{
          position: 'absolute', top: 42, left: 8,
          pointerEvents: 'auto',
        }}>
          <PostureMotionOverlay
            live2dRef={live2dRef}
            posture={posture}
            setPosture={setPostureState}
            motionSpeed={motionSpeed}
            setMotionSpeed={setMotionSpeedState}
            actionDuration={actionDuration}
            setActionDuration={setActionDuration}
          />
        </div>
      </div>

      {/* Reply bubble */}
      {showBubble && reply && (
        <div
          onClick={() => setShowBubble(false)}
          style={{
            position: 'absolute', top: 42, left: 10, right: 10,
            maxHeight: 130, overflow: 'auto', zIndex: 25,
            background: 'rgba(15,23,42,0.75)', backdropFilter: 'blur(16px)',
            borderRadius: 10, padding: '8px 12px',
            color: '#e2e8f0', fontSize: 12, lineHeight: 1.5,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            border: '1px solid rgba(148,163,184,0.1)',
            cursor: 'pointer', pointerEvents: 'auto',
          }}
        >
          {reply}{loading && <span style={{ color: '#818cf8' }}>▍</span>}
        </div>
      )}

      {/* Input bar — visible on hover */}
      <div style={{
        position: 'absolute', bottom: 10, left: 10, right: 10, height: 42,
        display: 'flex', alignItems: 'center', gap: 6,
        background: 'rgba(15,23,42,0.6)', backdropFilter: 'blur(14px)',
        borderRadius: 21, padding: '0 6px 0 12px',
        border: '1px solid rgba(148,163,184,0.1)',
        opacity: transitioning ? 1 : 0,
        transition: 'opacity 0.35s ease',
        pointerEvents: transitioning ? 'auto' : 'none',
        zIndex: 25,
      }}>
        <input
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="说点什么…"
          disabled={loading}
          autoFocus={hovered}
          style={{
            flex: 1, height: 28, padding: 0, border: 'none',
            background: 'transparent', color: '#e2e8f0', fontSize: 12, outline: 'none',
          }}
        />
        <button
          onClick={toggleMic}
          disabled={processing}
          style={{
            width: 28, height: 28, borderRadius: '50%', border: 'none', flexShrink: 0,
            background: listening ? 'rgba(239,68,68,0.5)' : processing ? 'rgba(234,179,8,0.4)' : 'rgba(100,116,139,0.25)',
            color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13,
          }}
        >{processing ? '⏳' : listening ? '⏹' : '🎤'}</button>
        <button
          onClick={() => sendMessage()}
          disabled={loading || !inputText.trim()}
          style={{
            width: 28, height: 28, borderRadius: '50%', border: 'none', flexShrink: 0,
            background: loading ? 'rgba(99,102,241,0.2)' : 'rgba(99,102,241,0.45)',
            color: '#fff', cursor: loading ? 'default' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13,
          }}
        >→</button>
      </div>

      {/* Mic status */}
      {listening && (
        <div style={{
          position: 'absolute', bottom: 60, left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(239,68,68,0.65)', color: '#fff', fontSize: 10,
          padding: '3px 12px', borderRadius: 10, zIndex: 25,
          backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', gap: 4,
        }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#fca5a5' }} /> 录音中…
        </div>
      )}
      {processing && (
        <div style={{
          position: 'absolute', bottom: 60, left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(234,179,8,0.65)', color: '#fff', fontSize: 10,
          padding: '3px 12px', borderRadius: 10, zIndex: 25, backdropFilter: 'blur(8px)',
        }}>识别中…</div>
      )}

      {/* Settings */}
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
