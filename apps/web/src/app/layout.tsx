import type { Metadata } from 'next';
import Script from 'next/script';
import './globals.css';

export const metadata: Metadata = {
  title: 'PNN ASR — 语音识别',
  description: 'faster-whisper 实时语音识别',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="bg-canvas">
        <Script
          src="/live2d/libs/live2dcubismcore.min.js"
          strategy="beforeInteractive"
        />
        {children}
      </body>
    </html>
  );
}
