import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // TTS 首次合成可能超过 30s，避免开发代理 ECONNRESET
  experimental: {
    proxyTimeout: 300_000,
  },
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.watchOptions = {
        ...config.watchOptions,
        ignored: [
          '**/node_modules/**',
          '**/.git/**',
          'D:/**/System Volume Information/**',
          'D:/**/pagefile.sys',
          'D:/**/DumpStack.log.tmp',
        ],
      };
    }
    return config;
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8765/api/:path*',
      },
      {
        source: '/ws/:path*',
        destination: 'http://127.0.0.1:8765/ws/:path*',
      },
    ];
  },
};

export default nextConfig;
