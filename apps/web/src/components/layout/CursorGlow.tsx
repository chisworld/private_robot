'use client';

import { useEffect, useState } from 'react';

export function CursorGlow() {
  const [pos, setPos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const onMove = (e: MouseEvent) => setPos({ x: e.clientX, y: e.clientY });
    window.addEventListener('mousemove', onMove);
    return () => window.removeEventListener('mousemove', onMove);
  }, []);

  return (
    <div
      className="pointer-events-none fixed z-[2] h-80 w-80 -translate-x-1/2 -translate-y-1/2 rounded-full opacity-30 mix-blend-screen blur-3xl transition-transform duration-300 ease-out"
      style={{
        left: pos.x,
        top: pos.y,
        background:
          'radial-gradient(circle, rgba(99,102,241,0.35) 0%, rgba(124,58,237,0.15) 40%, transparent 70%)',
      }}
      aria-hidden
    />
  );
}
