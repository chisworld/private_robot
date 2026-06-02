import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '14酱 — 桌面宠物',
};

export default function PetLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
