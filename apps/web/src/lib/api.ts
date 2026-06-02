export interface AsrConfig {
  model: string;
  model_path: string | null;
  device: string;
  compute_type: string;
  language: string | null;
  silence_duration: number;
  partial_interval: number;
  energy_threshold: number | null;
  active_threshold?: number | null;
  status: string;
  loading: boolean;
  resolved_device: string | null;
  last_error: string | null;
  model_multilingual?: boolean;
  model_warning?: string | null;
}

export interface LanguageOption {
  code: string;
  label: string;
}

export interface ModelsResponse {
  models: string[];
  languages: LanguageOption[];
}

export type AsrWsMessage =
  | { type: 'status'; status: string }
  | { type: 'partial'; text: string }
  | { type: 'final'; text: string }
  | { type: 'error'; message: string }
  | { type: 'level'; energy: number; threshold: number; is_speech: boolean };

const DEFAULT_BACKEND = 'http://127.0.0.1:8765';

/** 浏览器走同源 + next.config 代理；SSR 直连后端。 */
export function getApiBase(): string {
  if (typeof window !== 'undefined') {
    return process.env.NEXT_PUBLIC_ASR_API_URL ?? window.location.origin;
  }
  return process.env.NEXT_PUBLIC_ASR_API_URL ?? DEFAULT_BACKEND;
}

/** TTS 合成/启动耗时长，浏览器直连 8765，避免 Next 开发代理 socket hang up。 */
export function getDirectApiBase(): string {
  return (
    process.env.NEXT_PUBLIC_API_DIRECT_URL ??
    process.env.NEXT_PUBLIC_ASR_API_URL ??
    DEFAULT_BACKEND
  );
}

function getWsUrl(): string {
  if (typeof window !== 'undefined') {
    if (process.env.NEXT_PUBLIC_ASR_WS_URL) {
      return process.env.NEXT_PUBLIC_ASR_WS_URL;
    }
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}/ws/asr`;
  }
  return process.env.NEXT_PUBLIC_ASR_WS_URL ?? 'ws://127.0.0.1:8765/ws/asr';
}

async function parseError(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const json = JSON.parse(text) as { detail?: string | { msg: string }[] };
    if (typeof json.detail === 'string') return json.detail;
    if (Array.isArray(json.detail)) return json.detail.map((d) => d.msg).join('; ');
  } catch {
    // ignore
  }
  return text || res.statusText || '请求失败';
}

async function request<T>(
  path: string,
  init?: RequestInit,
  options?: { direct?: boolean },
): Promise<T> {
  const base = options?.direct ? getDirectApiBase() : getApiBase();
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<T>;
}

export const asrApi = {
  health: () => request<{ status: string }>('/api/health'),
  getModels: () => request<ModelsResponse>('/api/models'),
  getConfig: () => request<AsrConfig>('/api/config'),
  updateConfig: (body: Partial<AsrConfig>) =>
    request<AsrConfig>('/api/config', { method: 'PUT', body: JSON.stringify(body) }),
  startStream: () => request<{ ok: boolean; status: string }>('/api/stream/start', { method: 'POST' }),
  stopStream: () => request<{ ok: boolean }>('/api/stream/stop', { method: 'POST' }),
  transcribeFile: async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${getApiBase()}/api/transcribe`, { method: 'POST', body: form });
    if (!res.ok) throw new Error(await parseError(res));
    return res.json() as Promise<{ text: string; language: string; duration: number }>;
  },
};

export function createAsrWebSocket(onMessage: (msg: AsrWsMessage) => void) {
  const ws = new WebSocket(getWsUrl());
  ws.onmessage = (event) => {
    onMessage(JSON.parse(event.data) as AsrWsMessage);
  };
  return ws;
}

// ── TTS ──────────────────────────────────────────────────────────────────────

export interface EmotionPreset {
  id: string;
  label: string;
  ref_audio_path: string;
  prompt_text: string;
  prompt_lang: string;
}

export interface TtsConfig {
  provider: string;
  server_url: string;
  work_path: string | null;
  api_key: string;
  gpt_model_path: string;
  sovits_model_path: string;
  ref_audio_path: string;
  prompt_text: string;
  prompt_lang: string;
  text_lang: string;
  speed_factor: number;
  auto_start_server: boolean;
  character_name: string;
  onnx_model_dir: string;
  emotion_presets: EmotionPreset[];
  active_emotion_id: string;
  server_alive: boolean;
  last_error: string | null;
  service_version?: number;
}

export interface TtsProviderOption {
  id: string;
  label: string;
}

export interface TtsHealthResponse {
  ok: boolean;
  server_url: string;
  status?: string;
  error?: string;
}

export interface PickPathResponse {
  path: string | null;
  cancelled: boolean;
}

export const dialogApi = {
  pickFile: (body: { title?: string; filetypes?: [string, string][]; initial_dir?: string }) =>
    request<PickPathResponse>('/api/dialog/pick-file', { method: 'POST', body: JSON.stringify(body) }),
  pickFolder: (body: { title?: string; initial_dir?: string }) =>
    request<PickPathResponse>('/api/dialog/pick-folder', { method: 'POST', body: JSON.stringify(body) }),
};

// ── Chat / LLM ───────────────────────────────────────────────────────────────

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  at: number;
  streaming?: boolean;
}

export interface CharacterSummary {
  id: string;
  name: string;
}

export interface CharacterConfig {
  id: string;
  name: string;
  character_prompt: string;
}

export interface LlmConfig {
  api_key: string;
  api_key_masked: string;
  base_url: string;
  model: string;
  system_prompt: string;
  active_character: string;
  temperature: number;
  max_tokens: number;
  max_history_messages: number;
  configured: boolean;
  last_error: string | null;
  stream_sse_version?: number;
  characters?: CharacterSummary[];
}

/** 分句：按句号切段合成；整段：全文合成一次，段间无停顿 */
export type TtsSpeakMode = 'sentence' | 'full';

export type ChatStreamEvent =
  | { delta: string }
  | { done: true }
  | { error: string };

export interface ChatCompletionResponse {
  reply: string;
  model?: string;
  usage?: Record<string, number>;
}

export type BackendProbeResult =
  | { ok: true }
  | { ok: false; reason: 'down' }
  | { ok: false; reason: 'stale_api' };

/** 必须能访问对话配置接口，避免旧版 API（仅有 health）误判为就绪。 */
export async function probeBackend(): Promise<BackendProbeResult> {
  const base = getApiBase();
  try {
    const cfgRes = await fetch(`${base}/api/chat/config`, { cache: 'no-store' });
    if (cfgRes.ok) return { ok: true };
    if (cfgRes.status === 404) return { ok: false, reason: 'stale_api' };
  } catch {
    // fall through
  }
  try {
    const healthRes = await fetch(`${base}/api/health`, { cache: 'no-store' });
    if (healthRes.ok) return { ok: false, reason: 'stale_api' };
  } catch {
    // fall through
  }
  return { ok: false, reason: 'down' };
}

export async function waitForBackend(maxAttempts = 20, intervalMs = 800): Promise<BackendProbeResult> {
  for (let i = 0; i < maxAttempts; i += 1) {
    const result = await probeBackend();
    if (result.ok) return result;
    if (result.reason === 'stale_api') return result;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return { ok: false, reason: 'down' };
}

export function backendErrorMessage(result: BackendProbeResult): string {
  if (result.ok) return '';
  if (result.reason === 'stale_api') {
    return (
      '检测到旧版 API（8765 端口）。请关闭所有黑色命令行窗口，' +
      '重新双击 start.bat，等待「API 已就绪」后再刷新本页。'
    );
  }
  return (
    '后端 API 未启动。请在 pnn_garden 目录双击 start.bat，' +
    '等待控制台出现「API 已就绪」后再刷新。'
  );
}

export const chatApi = {
  getConfig: () => request<LlmConfig>('/api/chat/config', undefined, { direct: true }),
  reloadConfig: () =>
    request<LlmConfig>('/api/chat/config/reload', { method: 'POST' }, { direct: true }),
  updateConfig: (body: Partial<LlmConfig> & { api_key?: string }) =>
    request<LlmConfig>(
      '/api/chat/config',
      { method: 'PUT', body: JSON.stringify(body) },
      { direct: true },
    ),
  listCharacters: () =>
    request<{ characters: CharacterSummary[] }>('/api/chat/characters', undefined, {
      direct: true,
    }),
  getCharacter: (id: string) =>
    request<CharacterConfig>(`/api/chat/characters/${encodeURIComponent(id)}`, undefined, {
      direct: true,
    }),
  saveCharacter: (id: string, body: { name?: string; character_prompt?: string }) =>
    request<CharacterConfig>(
      `/api/chat/characters/${encodeURIComponent(id)}`,
      { method: 'PUT', body: JSON.stringify(body) },
      { direct: true },
    ),
  createCharacter: (body: { id: string; name?: string; character_prompt?: string }) =>
    request<CharacterConfig>('/api/chat/characters', {
      method: 'POST',
      body: JSON.stringify(body),
    }, { direct: true }),
  complete: (
    message: string,
    history: { role: 'user' | 'assistant'; content: string }[],
    signal?: AbortSignal,
  ) =>
    request<ChatCompletionResponse>('/api/chat/completions', {
      method: 'POST',
      body: JSON.stringify({ message, history }),
      signal,
    }, { direct: true }),
  streamComplete: async function* (
    message: string,
    history: { role: 'user' | 'assistant'; content: string }[],
    signal?: AbortSignal,
  ): AsyncGenerator<string, void, undefined> {
    const res = await fetch(`${getDirectApiBase()}/api/chat/completions/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, history }),
      signal,
    });
    if (!res.ok) {
      throw new Error(await parseError(res));
    }
    if (!res.body) {
      throw new Error('流式响应为空');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() ?? '';

      for (const block of blocks) {
        for (const line of block.split('\n')) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const jsonStr = trimmed.replace(/^data:\s*/, '');
          if (!jsonStr) continue;
          let payload: ChatStreamEvent;
          try {
            payload = JSON.parse(jsonStr) as ChatStreamEvent;
          } catch {
            continue;
          }
          if ('error' in payload && payload.error) {
            throw new Error(payload.error);
          }
          if ('delta' in payload && payload.delta) {
            yield payload.delta;
          }
          if ('done' in payload && payload.done) {
            return;
          }
        }
      }
    }
  },
};

async function directRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const base = getDirectApiBase();
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<T>;
}

const ttsRequest = <T>(path: string, init?: RequestInit) =>
  request<T>(path, init, { direct: true });

export const ttsApi = {
  getLanguages: () => ttsRequest<{ languages: LanguageOption[] }>('/api/tts/languages'),
  getProviders: () => ttsRequest<{ providers: TtsProviderOption[] }>('/api/tts/providers'),
  getConfig: () => ttsRequest<TtsConfig>('/api/tts/config'),
  updateConfig: (body: Partial<TtsConfig>) =>
    ttsRequest<TtsConfig>('/api/tts/config', { method: 'PUT', body: JSON.stringify(body) }),
  health: () => ttsRequest<TtsHealthResponse>('/api/tts/health'),
  startServer: () =>
    ttsRequest<TtsHealthResponse>('/api/tts/server/start', { method: 'POST' }),
  stopServer: () => ttsRequest<{ ok: boolean }>('/api/tts/server/stop', { method: 'POST' }),
  referencePreviewUrl: (path: string) =>
    `${getDirectApiBase()}/api/tts/reference/preview?path=${encodeURIComponent(path)}`,
  synthesize: async (text: string, textLang?: string, emotionId?: string) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 300_000);
    try {
      const res = await fetch(`${getDirectApiBase()}/api/tts/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          text_lang: textLang,
          emotion_id: emotionId || undefined,
        }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(await parseError(res));
      return res.blob();
    } catch (e) {
      if (e instanceof Error && e.name === 'AbortError') {
        throw new Error('TTS 合成超时（超过 5 分钟），请检查 GPT-SoVITS 是否正常运行');
      }
      if (e instanceof TypeError && String(e.message).includes('fetch')) {
        throw new Error(
          '无法连接 TTS 后端（8765）。请确认 start.bat 已启动且控制台显示 API 已就绪。',
        );
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  },
};
