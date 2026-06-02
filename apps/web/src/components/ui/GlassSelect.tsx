'use client';

import type { SelectHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

export interface GlassSelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  hint?: string;
}

export function GlassSelect({ label, hint, className, children, ...props }: GlassSelectProps) {
  return (
    <label className="flex flex-col gap-2">
      <span className="text-xs font-medium uppercase tracking-widest text-slate-400">{label}</span>
      <select
        className={cn(
          'rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3 text-sm tracking-wide text-slate-100',
          'outline-none transition-all duration-300',
          'focus:border-indigo-400/60 focus:shadow-[0_0_0_3px_rgba(99,102,241,0.25)]',
          'disabled:cursor-not-allowed disabled:opacity-50',
          className,
        )}
        {...props}
      >
        {children}
      </select>
      {hint && <span className="text-xs tracking-wide text-slate-500">{hint}</span>}
    </label>
  );
}
