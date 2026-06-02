'use client';

import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

export interface PrimaryButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: 'primary' | 'ghost';
}

export function PrimaryButton({
  children,
  className,
  variant = 'primary',
  disabled,
  ...props
}: PrimaryButtonProps) {
  if (variant === 'ghost') {
    return (
      <button
        type="button"
        disabled={disabled}
        className={cn(
          'rounded-2xl border border-white/15 bg-slate-900/60 px-6 py-3 text-sm font-medium tracking-wide',
          'transition-all duration-300 hover:border-white/30 hover:bg-slate-900/80',
          'disabled:cursor-not-allowed disabled:opacity-40',
          className,
        )}
        {...props}
      >
        {children}
      </button>
    );
  }

  return (
    <button
      type="button"
      disabled={disabled}
      className={cn(
        'shimmer-btn relative overflow-hidden rounded-2xl px-8 py-3 text-sm font-semibold tracking-wide text-white',
        'bg-gradient-to-r from-indigo-600 to-purple-600',
        'transition-all duration-300 hover:scale-105 hover:shadow-[0_0_40px_rgba(124,58,237,0.5)]',
        'disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100',
        className,
      )}
      {...props}
    >
      <span className="relative z-10">{children}</span>
    </button>
  );
}
