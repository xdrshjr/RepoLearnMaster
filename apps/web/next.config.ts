import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The BFF talks to a local FastAPI process on 127.0.0.1:8000. Nothing in the
  // browser ever needs to know that address (spec §2.2 constraint 6).
  experimental: {
    // Keep server actions payload small; the web app does not use them, but the
    // limit also guards against accidental large-body BFF misuse.
    serverActions: { bodySizeLimit: '2mb' },
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
        ],
      },
    ];
  },
};

export default nextConfig;
