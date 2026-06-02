'use client';

import { useRef, useState } from 'react';
import { FolderOpen, Loader2 } from 'lucide-react';
import { dialogApi } from '@/lib/api';
import { PrimaryButton } from '@/components/ui/PrimaryButton';
import { cn } from '@/lib/cn';

export interface PathPickerFieldProps {
  label: string;
  value: string;
  onChange: (path: string) => void;
  disabled?: boolean;
  hint?: string;
  placeholder?: string;
  mode: 'file' | 'folder';
  dialogTitle?: string;
  filetypes?: [string, string][];
}

export function PathPickerField({
  label,
  value,
  onChange,
  disabled,
  hint,
  placeholder,
  mode,
  dialogTitle,
  filetypes,
}: PathPickerFieldProps) {
  const [picking, setPicking] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const browse = async () => {
    if (disabled || picking) return;
    setPicking(true);
    try {
      const initialDir = value.trim() || undefined;
      const result =
        mode === 'folder'
          ? await dialogApi.pickFolder({
              title: dialogTitle ?? '选择文件夹',
              initial_dir: initialDir,
            })
          : await dialogApi.pickFile({
              title: dialogTitle ?? '选择文件',
              initial_dir: initialDir,
              filetypes: filetypes ?? [['All files', '*.*']],
            });
      if (!result.cancelled && result.path) {
        onChange(result.path);
      }
    } finally {
      setPicking(false);
    }
  };

  return (
    <label className="flex flex-col gap-2">
      <span className="text-xs font-medium uppercase tracking-widest text-slate-400">{label}</span>
      <div className="flex gap-2">
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          placeholder={placeholder}
          className={cn(
            'min-w-0 flex-1 rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3 text-sm tracking-wide text-slate-100',
            'outline-none transition-all duration-300',
            'focus:border-indigo-400/60 focus:shadow-[0_0_0_3px_rgba(99,102,241,0.25)]',
            'disabled:cursor-not-allowed disabled:opacity-50',
          )}
        />
        <PrimaryButton
          type="button"
          variant="ghost"
          onClick={() => void browse()}
          disabled={disabled || picking}
          className="shrink-0 px-4"
          title={mode === 'folder' ? '选择文件夹' : '选择文件'}
        >
          {picking ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderOpen className="h-4 w-4" />}
        </PrimaryButton>
      </div>
      {hint && <span className="text-xs tracking-wide text-slate-500">{hint}</span>}
    </label>
  );
}
