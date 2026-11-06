import { Suspense } from 'react';

import { CourseShell } from '@/components/shell/course-shell';
import { Skeleton } from '@/components/ui/card';

/**
 * Workbench shell for P03–P05 + P08 (spec §7.2).
 *
 * The layout (and therefore the player) is preserved across tab navigation,
 * which is the whole reason the audio element lives here and not in a page.
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
  );
}
