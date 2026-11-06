import { Suspense } from 'react';

import { CourseShell } from '@/components/shell/course-shell';
import { UpdateBanner } from '@/components/shell/update-banner';
import { Skeleton } from '@/components/ui/card';

/**
 * Workbench shell for P03–P05 + P08 (spec §7.2).
 *
 * The layout (and therefore the player) is preserved across tab navigation,
 * which is the whole reason the audio element lives here and not in a page.
 *
 * 顶部多了一条 `UpdateBanner`（spec §3.5.4 / §4.4 #70）：它讲的是"仓库有新的
 * commit"，与 `/rebuild`（同一 commit、对内容不满意重跑）是两件不同的事，因此
 * 入口必须常驻在工作台而不是藏在设置里。
 */
export default async function CourseLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-bg">
      <Suspense fallback={<div className="h-8 shrink-0 border-b border-border bg-bg-elevated" />}>
        <UpdateBanner courseId={courseId} />
      </Suspense>
      {/*
        `[&>*]:!h-full` 是有意为之：`CourseShell` 自己的根节点写着 `h-dvh`
        （它为整个工作台占满一屏）。现在它下面多了一条横幅，若仍按 100dvh 渲染，
        底部播放器会被挤出容器 28px 并被 `overflow-hidden` 剪掉——而播放器是这门
        课最不能消失的东西。这里只约束**直接子元素**的高度，不改 `CourseShell`。
      */}
      <div className="min-h-0 flex-1 [&>*]:!h-full">
        <Suspense
          fallback={
            <div className="space-y-3 p-4">
              <Skeleton className="h-10" />
              <Skeleton className="h-64" />
            </div>
          }
        >
          <CourseShell courseId={courseId}>{children}</CourseShell>
        </Suspense>
      </div>
    </div>
  );
}
