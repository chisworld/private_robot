'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { EmotionPreset, TtsConfig } from '@/lib/api';

export type TtsDraft = {
  provider: string;
  server_url: string;
  work_path: string;
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
};

export const EMPTY_TTS_DRAFT: TtsDraft = {
  provider: 'gpt-sovits',
  server_url: 'http://127.0.0.1:9880',
  work_path: '',
  api_key: '',
  gpt_model_path: '',
  sovits_model_path: '',
  ref_audio_path: '',
  prompt_text: '',
  prompt_lang: 'zh',
  text_lang: 'zh',
  speed_factor: 1,
  auto_start_server: true,
  character_name: '',
  onnx_model_dir: '',
  emotion_presets: [],
  active_emotion_id: '',
};

function newPresetId(): string {
  return `emotion_${Date.now().toString(36)}`;
}

export function configToDraft(config: TtsConfig): TtsDraft {
  const presets = config.emotion_presets?.length
    ? config.emotion_presets
    : config.ref_audio_path || config.prompt_text
      ? [
          {
            id: 'default',
            label: '默认',
            ref_audio_path: config.ref_audio_path ?? '',
            prompt_text: config.prompt_text ?? '',
            prompt_lang: config.prompt_lang ?? '',
          },
        ]
      : [];

  return {
    provider: config.provider,
    server_url: config.server_url,
    work_path: config.work_path ?? '',
    api_key: config.api_key ?? '',
    gpt_model_path: config.gpt_model_path ?? '',
    sovits_model_path: config.sovits_model_path ?? '',
    ref_audio_path: config.ref_audio_path ?? '',
    prompt_text: config.prompt_text ?? '',
    prompt_lang: config.prompt_lang ?? 'zh',
    text_lang: config.text_lang ?? 'zh',
    speed_factor: config.speed_factor ?? 1,
    auto_start_server: config.auto_start_server ?? true,
    character_name: config.character_name ?? '',
    onnx_model_dir: config.onnx_model_dir ?? '',
    emotion_presets: presets,
    active_emotion_id: config.active_emotion_id || presets[0]?.id || '',
  };
}

export function draftToPatch(draft: TtsDraft): Partial<TtsConfig> {
  const presets = draft.emotion_presets.map((item) => ({
    ...item,
    ref_audio_path:
      item.id === draft.active_emotion_id ? draft.ref_audio_path.trim() : item.ref_audio_path.trim(),
    prompt_text:
      item.id === draft.active_emotion_id ? draft.prompt_text.trim() : item.prompt_text.trim(),
    prompt_lang: item.id === draft.active_emotion_id ? draft.prompt_lang : item.prompt_lang,
  }));

  return {
    provider: draft.provider,
    server_url: draft.server_url.trim(),
    work_path: draft.work_path.trim() || null,
    api_key: draft.api_key.trim(),
    gpt_model_path: draft.gpt_model_path.trim(),
    sovits_model_path: draft.sovits_model_path.trim(),
    ref_audio_path: draft.ref_audio_path.trim(),
    prompt_text: draft.prompt_text.trim(),
    prompt_lang: draft.prompt_lang,
    text_lang: draft.text_lang,
    speed_factor: draft.speed_factor,
    auto_start_server: draft.auto_start_server,
    character_name: draft.character_name.trim(),
    onnx_model_dir: draft.onnx_model_dir.trim(),
    emotion_presets: presets,
    active_emotion_id: draft.active_emotion_id,
  };
}

function applyPresetToDraft(draft: TtsDraft, presetId: string): TtsDraft {
  const preset = draft.emotion_presets.find((item) => item.id === presetId);
  if (!preset) return draft;
  return {
    ...draft,
    active_emotion_id: presetId,
    ref_audio_path: preset.ref_audio_path,
    prompt_text: preset.prompt_text,
    prompt_lang: preset.prompt_lang || draft.prompt_lang,
  };
}

export function useTtsDraft(config: TtsConfig | null, onSave: (patch: Partial<TtsConfig>) => Promise<unknown>) {
  const [draft, setDraft] = useState<TtsDraft>(EMPTY_TTS_DRAFT);
  const hydratedRef = useRef(false);

  useEffect(() => {
    if (!config || hydratedRef.current) return;
    setDraft(configToDraft(config));
    hydratedRef.current = true;
  }, [config]);

  const patchDraft = useCallback(<K extends keyof TtsDraft>(key: K, value: TtsDraft[K]) => {
    setDraft((prev) => {
      const next = { ...prev, [key]: value };
      if (
        prev.active_emotion_id &&
        (key === 'ref_audio_path' || key === 'prompt_text' || key === 'prompt_lang')
      ) {
        next.emotion_presets = prev.emotion_presets.map((item) =>
          item.id === prev.active_emotion_id
            ? {
                ...item,
                ref_audio_path: key === 'ref_audio_path' ? String(value) : item.ref_audio_path,
                prompt_text: key === 'prompt_text' ? String(value) : item.prompt_text,
                prompt_lang: key === 'prompt_lang' ? String(value) : item.prompt_lang,
              }
            : item,
        );
      }
      return next;
    });
  }, []);

  const selectEmotion = useCallback((presetId: string) => {
    setDraft((prev) => applyPresetToDraft(prev, presetId));
  }, []);

  const updateActiveLabel = useCallback((label: string) => {
    setDraft((prev) => ({
      ...prev,
      emotion_presets: prev.emotion_presets.map((item) =>
        item.id === prev.active_emotion_id ? { ...item, label } : item,
      ),
    }));
  }, []);

  const addEmotion = useCallback(() => {
    setDraft((prev) => {
      const id = newPresetId();
      const preset: EmotionPreset = {
        id,
        label: `情绪 ${prev.emotion_presets.length + 1}`,
        ref_audio_path: '',
        prompt_text: '',
        prompt_lang: prev.prompt_lang,
      };
      return applyPresetToDraft({ ...prev, emotion_presets: [...prev.emotion_presets, preset] }, id);
    });
  }, []);

  const removeActiveEmotion = useCallback(() => {
    setDraft((prev) => {
      if (prev.emotion_presets.length <= 1) return prev;
      const remaining = prev.emotion_presets.filter((item) => item.id !== prev.active_emotion_id);
      const nextId = remaining[0]?.id ?? '';
      return applyPresetToDraft({ ...prev, emotion_presets: remaining }, nextId);
    });
  }, []);

  const saveDraft = useCallback(async () => {
    const next = await onSave(draftToPatch(draft));
    if (next && typeof next === 'object' && 'provider' in next) {
      setDraft(configToDraft(next as TtsConfig));
    }
  }, [draft, onSave]);

  const applySavedConfig = useCallback((saved: TtsConfig) => {
    setDraft(configToDraft(saved));
  }, []);

  return {
    draft,
    patchDraft,
    selectEmotion,
    updateActiveLabel,
    addEmotion,
    removeActiveEmotion,
    saveDraft,
    applySavedConfig,
  };
}
