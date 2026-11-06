import type { Metadata } from 'next';
import { Suspense } from 'react';

import { PrepareView } from '@/components/prepare/prepare-view';
import { SiteHeader } from '@/components/shell/site-header';
import { Skeleton } from '@/components/ui/card';

export const metadata: Metadata = {
  title: '课程准备',
};

/**
 * P02 课程准备 — spec §7.2.
 *
 * The route is `repo/[owner]/[name]`, exactly as the home page redirects after
 * `POST /api/courses` (spec §7.2 首页 / §3.9 S2).
 */
export default async function RepoPreparePage({
  params,
}: {
  params: Promise<{ owner: string; name: string }>;
}) {
  const { owner, name } = await params;

  return (
    <>
      <SiteHeader context={`${owner}/${name}`} />
      <Suspense
        fallback={
          <main className="mx-auto w-full max-w-[1100px] space-y-3 px-4 py-6">
            <Skeleton className="h-10 w-64" />
            <Skeleton className="h-40" />
            <Skeleton className="h-28" />
          </main>
        }
      >
        <PrepareView owner={owner} name={name} />
      </Suspense>
    </>
  );
}
