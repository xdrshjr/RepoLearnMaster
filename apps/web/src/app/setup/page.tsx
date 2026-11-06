import type { Metadata } from 'next';
import { Suspense } from 'react';

import { SetupWizard } from '@/components/setup/setup-wizard';
import { SiteHeader } from '@/components/shell/site-header';
import { Skeleton } from '@/components/ui/card';

export const metadata: Metadata = {
  title: '配置 AI 服务',
  description: '五步完成模型服务、连通性、语音、角色与提交。',
};

// The wizard must never be served from a shared cache: the first-run decision is
// per-browser state, not static content.
export const dynamic = 'force-dynamic';

/**
 * `/setup` — first-run wizard (spec §3.6).
 *
 * Not wrapped by the setup guard: this is the whitelisted landing page, and it
 * verifies real state client-side so a stale cookie can never loop.
 */
export default function SetupPage() {
  return (
    <>
      <SiteHeader context="首次配置 · 大约 1 分钟" />
      <main id="main">
        <Suspense
          fallback={
            <div className="mx-auto w-full max-w-[860px] space-y-3 px-4 py-10">
              <Skeleton className="h-8 w-52" />
              <Skeleton className="h-56" />
            </div>
          }
        >
          <SetupWizard />
        </Suspense>
      </main>
    </>
  );
}
