'use client';

import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export interface GlassCardProps {
  children: ReactNode;
  className?: string;
  hoverable?: boolean;
}

export function GlassCard({ children, className, hoverable = true }: GlassCardProps) {
  return (
    <div
      data-component="glass-card"
      className={cn(
        'glass-rim rounded-glass border border-white/10 bg-white/5 p-8 backdrop-blur-glass',
        'shadow-[inset_0_1px_1px_0_rgba(255,255,255,0.05)]',
        hoverable && 'transition-[border-color,box-shadow] duration-400 hover:border-white/25',
        className,
      )}
    >
      {children}
    </div>
  );
}
