'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Check, KeyRound, Settings2, UserCircle } from 'lucide-react';
import { GlassCard } from '@/components/ui/GlassCard';
import { GlassInput, GlassTextarea } from '@/components/ui/GlassInput';
import { GlassSelect } from '@/components/ui/GlassSelect';
import { PrimaryButton } from '@/components/ui/PrimaryButton';
import { restoreVariants } from '@/components/ui/motion-presets';
import { chatApi, type CharacterSummary, type LlmConfig } from '@/lib/api';

interface ChatConfigPanelProps {
  config: LlmConfig | null;
  saving: boolean;
  onSave: (patch: Partial<LlmConfig> & { api_key?: string }) => Promise<LlmConfig>;
}

export function ChatConfigPanel({ config, saving, onSave }: ChatConfigPanelProps) {
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('https://api.deepseek.com');
  const [model, setModel] = useState('deepseek-chat');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [activeCharacter, setActiveCharacter] = useState('');
  const [characterName, setCharacterName] = useState('');
  const [characterPrompt, setCharacterPrompt] = useState('');
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
  const [saveOk, setSaveOk] = useState(false);
  const [charLoading, setCharLoading] = useState(false);
  const [charsApiMissing, setCharsApiMissing] = useState(false);
  const hydratedRef = useRef(false);

  const mergeCharacterOptions = useCallback(
    (list: CharacterSummary[], activeId?: string) => {
      const merged = [...list];
      const id = (activeId || '').trim();
      if (id && !merged.some((c) => c.id === id)) {
        merged.unshift({ id, name: id });
      }
      return merged;
    },
    [],
  );

  const refreshCharacterList = useCallback(
    async (activeId?: string) => {
      const fallbackId = (activeId || config?.active_character || '').trim();
      try {
        const { characters: list } = await chatApi.listCharacters();
        const merged = mergeCharacterOptions(list, fallbackId);
        setCharacters(merged);
        return merged;
      } catch {
        const fromConfig = config?.characters ?? [];
        const merged = mergeCharacterOptions(fromConfig, fallbackId);
        setCharacters(merged);
        return merged;
      }
    },
    [config?.active_character, config?.characters, mergeCharacterOptions],
  );

  const loadCharacterIntoForm = useCallback(async (charId: string) => {
    if (!charId) {
      setCharacterName('');
      setCharacterPrompt('');
      return;
    }
    setCharLoading(true);
    try {
      const ch = await chatApi.getCharacter(charId);
      setCharacterName(ch.name);
      setCharacterPrompt(ch.character_prompt);
    } catch {
      setCharacterName(charId);
      setCharacterPrompt('');
    } finally {
      setCharLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!config || hydratedRef.current) return;
    setBaseUrl(config.base_url);
    setModel(config.model);
    setSystemPrompt(config.system_prompt ?? '');
    const activeId = config.active_character ?? '';
    setActiveCharacter(activeId);
    setCharacters(mergeCharacterOptions(config.characters ?? [], activeId));
    hydratedRef.current = true;
    void (async () => {
      let listOk = true;
      try {
        await chatApi.listCharacters();
      } catch {
        listOk = false;
        setCharsApiMissing(true);
      }
      const list = await refreshCharacterList(activeId);
      if (activeId && list.some((c) => c.id === activeId)) {
        await loadCharacterIntoForm(activeId);
      } else if (activeId && listOk) {
        setActiveCharacter(activeId);
      }
    })();
  }, [config, loadCharacterIntoForm, mergeCharacterOptions, refreshCharacterList]);

  const handleCharacterChange = (charId: string) => {
    setSaveOk(false);
    setActiveCharacter(charId);
    void loadCharacterIntoForm(charId);
  };

  return (
    <motion.div variants={restoreVariants} className="col-span-12 lg:col-span-4">
      <GlassCard>
        <div className="mb-6 flex items-center gap-3">
          <Settings2 className="h-5 w-5 text-indigo-300" />
          <h2 className="text-xl font-semibold tracking-headline text-white">DeepSeek</h2>
        </div>

        <div className="grid gap-5">
          <GlassInput
            label="API Key"
            type="password"
            value={apiKey}
            disabled={saving}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={config?.configured ? `已配置 ${config.api_key_masked}` : 'sk-…'}
            hint="也可设置环境变量 DEEPSEEK_API_KEY 或项目根目录 local_config.py"
          />
          <GlassInput
            label="API 地址"
            value={baseUrl}
            disabled={saving}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
          <GlassInput
            label="模型"
            value={model}
            disabled={saving}
            onChange={(e) => setModel(e.target.value)}
            hint="例如 deepseek-chat、deepseek-reasoner"
          />

          <div className="border-t border-white/10 pt-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium text-slate-200">
              <UserCircle className="h-4 w-4 text-emerald-300" />
              人物设定
            </div>
            {charsApiMissing && (
              <p className="mb-3 rounded-2xl border border-amber-400/25 bg-amber-400/10 px-3 py-2 text-xs text-amber-200">
                角色列表接口未就绪：请关闭旧窗口后重新运行 start.bat，再刷新本页。
              </p>
            )}
            <GlassSelect
              label="当前角色"
              value={activeCharacter}
              disabled={saving || charLoading}
              onChange={(e) => handleCharacterChange(e.target.value)}
              hint="对应 data/config/角色名.json（如 树里亚.json）"
            >
              <option value="">（不加载角色文件）</option>
              {characters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name || c.id}
                </option>
              ))}
            </GlassSelect>
            {activeCharacter && (
              <>
                <GlassInput
                  label="角色显示名"
                  value={characterName}
                  disabled={saving || charLoading}
                  onChange={(e) => {
                    setSaveOk(false);
                    setCharacterName(e.target.value);
                  }}
                  className="mt-4"
                />
                <GlassTextarea
                  label={`人物设定（data/config/${activeCharacter}.json）`}
                  value={characterPrompt}
                  disabled={saving || charLoading}
                  onChange={(e) => {
                    setSaveOk(false);
                    setCharacterPrompt(e.target.value);
                  }}
                  className="mt-4 min-h-[160px]"
                  placeholder="角色性格、口癖、背景等人设内容"
                />
              </>
            )}
          </div>

          <GlassTextarea
            label="输出规则（data/config/llm.json → system_prompt）"
            value={systemPrompt}
            disabled={saving}
            onChange={(e) => {
              setSaveOk(false);
              setSystemPrompt(e.target.value);
            }}
            className="min-h-[100px]"
            placeholder="语言、格式、禁止事项等硬性输出规则"
            hint="与人物设定分开保存；对话时两条 system 消息分别注入。"
          />

          <PrimaryButton
            className="inline-flex items-center gap-2"
            disabled={saving || charLoading}
            onClick={() => {
              void (async () => {
                try {
                  if (activeCharacter) {
                    await chatApi.saveCharacter(activeCharacter, {
                      name: characterName.trim() || activeCharacter,
                      character_prompt: characterPrompt,
                    });
                  }
                  const saved = await onSave({
                    ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
                    base_url: baseUrl.trim(),
                    model: model.trim(),
                    system_prompt: systemPrompt,
                    active_character: activeCharacter,
                  });
                  setBaseUrl(saved.base_url);
                  setModel(saved.model);
                  setSystemPrompt(saved.system_prompt ?? '');
                  setActiveCharacter(saved.active_character ?? '');
                  setApiKey('');
                  const merged = mergeCharacterOptions(
                    saved.characters ?? [],
                    saved.active_character ?? '',
                  );
                  setCharacters(merged);
                  setCharsApiMissing(false);
                  setSaveOk(true);
                } catch {
                  setSaveOk(false);
                }
              })();
            }}
          >
            <KeyRound className="h-4 w-4" />
            {saving ? '保存中…' : '保存全部配置'}
          </PrimaryButton>

          {saveOk && (
            <p className="flex items-center gap-2 rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-xs tracking-wide text-emerald-200">
              <Check className="h-3.5 w-3.5 shrink-0" />
              已保存。规则写入 llm.json，人设写入 {activeCharacter ? `${activeCharacter}.json` : '角色文件'}；下一条消息即生效。
            </p>
          )}

          {config && !config.configured && (
            <p className="rounded-2xl border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-xs tracking-wide text-amber-200">
              请先填写 API Key 才能开始对话。
            </p>
          )}
        </div>
      </GlassCard>
    </motion.div>
  );
}
