export function AmbientBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden" aria-hidden>
      <div className="absolute -left-32 -top-32 h-[520px] w-[520px] animate-float rounded-full bg-orb-indigo/20 blur-[180px]" />
      <div
        className="absolute right-0 top-1/3 h-[480px] w-[480px] animate-float rounded-full bg-orb-purple/15 blur-[180px]"
        style={{ animationDelay: '-4s' }}
      />
      <div
        className="absolute -bottom-24 left-1/4 h-[440px] w-[440px] animate-float rounded-full bg-orb-teal/10 blur-[180px]"
        style={{ animationDelay: '-8s' }}
      />
    </div>
  );
}
