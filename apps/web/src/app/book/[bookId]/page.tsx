import type { Metadata } from 'next';
import { Suspense } from 'react';

import { BookView } from '@/components/book/book-view';
import { Skeleton } from '@/components/ui/card';

export const metadata: Metadata = {
  title: '课程书籍',
};

/** P09 在线课程书籍 — spec §7.2. */
export default async function BookPage({ params }: { params: Promise<{ bookId: string }> }) {
  const { bookId } = await params;
  return (
    <Suspense
      fallback={
        <div className="space-y-3 p-4">
          <Skeleton className="h-10" />
          <Skeleton className="h-64" />
        </div>
      }
    >
      <BookView bookId={bookId} />
    </Suspense>
  );
}
