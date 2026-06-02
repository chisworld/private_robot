'use client';

const DISPLAY_MAX = 0.45;

interface VolumeMeterProps {
  level: number;
  threshold: number;
  isSpeech?: boolean;
}

function toPercent(value: number) {
  return Math.min(100, Math.max(0, (value / DISPLAY_MAX) * 100));
}

export function VolumeMeter({ level, threshold, isSpeech }: VolumeMeterProps) {
  const fillPct = toPercent(level);
  const thresholdPct = toPercent(threshold);

  return (
    <div className="flex flex-1 flex-col gap-2">
      <div className="relative h-3 overflow-hidden rounded-full border border-white/10 bg-slate-800/80">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-emerald-400 via-amber-400 to-red-500 will-change-[width]"
          style={{
            width: `${fillPct}%`,
            transition: 'width 60ms linear',
          }}
        />
        <div
          className="pointer-events-none absolute bottom-0 top-0 z-10 w-0.5 bg-white shadow-[0_0_6px_rgba(255,255,255,0.8)]"
          style={{ left: `calc(${thresholdPct}% - 1px)` }}
          title={`触发阈值 ${threshold.toFixed(3)}`}
        />
      </div>
      <div className="flex items-center justify-between text-[11px] tracking-wide text-slate-500">
        <span>音量 {level.toFixed(3)}</span>
        <span className={isSpeech ? 'text-indigo-300' : ''}>
          阈值 {threshold.toFixed(3)}
          {isSpeech ? ' · 已触发' : ''}
        </span>
      </div>
    </div>
  );
}
