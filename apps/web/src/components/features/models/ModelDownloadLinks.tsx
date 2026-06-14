'use client';

import { useEffect, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { modelsApi, type ModelDownloadEntry } from '@/lib/api';

interface ModelDownloadLinksProps {
  category: 'asr' | 'tts' | 'llm_local';
  title?: string;
  hint?: string;
}

export function ModelDownloadLinks({ category, title, hint }: ModelDownloadLinksProps) {
  const [entries, setEntries] = useState<ModelDownloadEntry[]>([]);
  const [hfEndpoint, setHfEndpoint] = useState('');

  useEffect(() => {
    modelsApi
      .getDownloads(category)
      .then((data) => {
        setEntries(data.entries);
        setHfEndpoint(data.hf_endpoint);
      })
      .catch(() => setEntries([]));
  }, [category]);

  if (!entries.length) return null;

  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/40 px-4 py-4">
      <h3 className="mb-2 text-sm font-semibold tracking-wide text-slate-200">
        {title ?? '模型下载'}
      </h3>
      {hint ? (
        <p className="mb-3 text-xs leading-relaxed tracking-wide text-slate-500">{hint}</p>
      ) : null}
      <ul className="space-y-3">
        {entries.map((entry) => (
          <li
            key={entry.id}
            className="rounded-xl border border-white/5 bg-slate-950/40 px-3 py-3 text-xs leading-relaxed text-slate-300"
          >
            <div className="font-medium text-slate-100">{entry.name}</div>
            <div className="mt-1 text-slate-500">安装路径：{entry.install_path}</div>
            {entry.description ? (
              <div className="mt-1 text-slate-500">{entry.description}</div>
            ) : null}
            <div className="mt-2 flex flex-wrap gap-3">
              {entry.links.map((link) => (
                <a
                  key={`${entry.id}-${link.url}`}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-indigo-300 hover:text-indigo-200"
                >
                  {link.label}
                  <ExternalLink className="h-3 w-3" />
                </a>
              ))}
            </div>
          </li>
        ))}
      </ul>
      {hfEndpoint ? (
        <p className="mt-3 text-[11px] tracking-wide text-slate-600">
          HuggingFace 镜像可在 .env 设置 HF_ENDPOINT（当前 {hfEndpoint}）。
        </p>
      ) : null}
    </div>
  );
}
