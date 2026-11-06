import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Build directory must be overridable (hardening spec P1-4): `start.ps1` runs
  // `next dev` on :3000 while `scripts/e2e-real.mjs` runs another one on :3100.
  // Two dev servers writing the same `.next` corrupt each other's build cache in
  // a way that looks like random white screens, so the e2e harness sets
  // REPOLEARN_NEXT_DIST_DIR=.next-e2e. Default stays `.next` for everyone else.
  distDir: process.env.REPOLEARN_NEXT_DIST_DIR || '.next',
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
