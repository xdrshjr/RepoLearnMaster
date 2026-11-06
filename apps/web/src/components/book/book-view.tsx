'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Bookmark, BookmarkCheck, FileDown } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Badge, Card, EmptyState, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { SiteHeader } from '@/components/shell/site-header';
import { BookReader, BookStatusBadge } from '@/components/book/book-reader';
import { ChapterNav } from '@/components/book/chapter-nav';
import { SearchPanel } from '@/components/book/search-panel';
import { useBook, useBookChapter } from '@/lib/api/hooks';
import { safeLocalStorageGet, safeLocalStorageSet } from '@/lib/utils';

/**
 * P09 在线课程书籍 — spec §7.2.
 *
 * Chapter nav + full-text search + code copy + “在课程中查看此代码” + font size
 * and theme controls. A generating book polls until it is ready.
 */
export function BookView({ bookId }: { bookId: string }) {
  const searchParams = useSearchParams();
  const book = useBook(bookId);
  const [chapterKey, setChapterKey] = useState<string | null>(searchParams.get('chapter'));
  const [bookmarks, setBookmarks] = useState<string[]>([]);

  useEffect(() => {
    const stored = safeLocalStorageGet(`rl_book_bookmarks_${bookId}`);
    if (!stored) return;
    try {
      const parsed: unknown = JSON.parse(stored);
      if (Array.isArray(parsed)) setBookmarks(parsed.filter((value): value is string => typeof value === 'string'));
    } catch {
      // A corrupted bookmark list is not worth an error state.
    }
  }, [bookId]);

  const persistBookmarks = (next: string[]) => {
    setBookmarks(next);
    safeLocalStorageSet(`rl_book_bookmarks_${bookId}`, JSON.stringify(next));
  };

  const activeKey = chapterKey ?? book.data?.chapters[0]?.key ?? null;
  const chapter = useBookChapter(bookId, activeKey);
  const courseId = book.data?.course_version_id ?? null;

  // Poll while the book is still generating (spec §7.2: status is visible).
  const bookStatus = book.data?.status;
  const refetchBook = book.refetch;
  useEffect(() => {
    if (!bookStatus || bookStatus === 'ready') return;
    const timer = window.setInterval(() => {
      void refetchBook();
    }, 4000);
    return () => window.clearInterval(timer);
  }, [bookStatus, refetchBook]);

  if (book.isError) {
    return (
      <>
        <SiteHeader context="课程书籍" />
        <main id="main" className="p-4">
          <EmptyState
            title="打不开这本书"
            description={book.error instanceof Error ? book.error.message : '书籍可能还在生成或已被清理。'}
            action={
              <Button variant="outline" size="sm" onClick={() => void book.refetch()}>
                重试
              </Button>
            }
          />
        </main>
      </>
    );
  }

  return (
    <>
      <SiteHeader
        context={book.data?.title ?? '课程书籍'}
        right={
          <Link
            href={`/book/${encodeURIComponent(bookId)}/pdf`}
            className="inline-flex items-center gap-1 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
          >
            <FileDown className="size-3.5" aria-hidden />
            PDF
          </Link>
        }
      />
      <div className="flex min-h-[calc(100dvh-48px)] flex-col">
        <div className="flex min-h-0 flex-1">
          <aside className="hidden w-[240px] shrink-0 border-r border-border bg-bg-elevated lg:block">
            <ChapterNav book={book.data} activeKey={activeKey} onSelect={setChapterKey} />
          </aside>

          <main id="main" className="min-w-0 flex-1 overflow-y-auto">
            {book.isLoading ? (
              <div className="space-y-3 p-4">
                <Skeleton className="h-7 w-1/2" />
                <Skeleton className="h-4" />
                <Skeleton className="h-40" />
              </div>
            ) : (
              <BookReader
                chapter={chapter.data}
                loading={chapter.isLoading}
                courseId={courseId}
                book={book.data}
                activeKey={activeKey}
                onSelectChapter={setChapterKey}
              />
            )}
          </main>

          <aside className="hidden w-[300px] shrink-0 space-y-3 border-l border-border bg-bg-elevated p-3 lg:block">
            <div className="flex items-center gap-2">
              <h2 className="text-xs font-semibold text-text">本书</h2>
              {book.data ? <BookStatusBadge status={book.data.status} /> : null}
            </div>
            {book.data ? (
              <p className="text-[10px] text-text-dim">
                preset {book.data.preset} · {book.data.word_count.toLocaleString()} 字
              </p>
            ) : null}

            <div className="flex flex-wrap gap-1">
              <Button
                variant={activeKey && bookmarks.includes(activeKey) ? 'primary' : 'outline'}
                size="sm"
                onClick={() => {
                  if (!activeKey) return;
                  const next = bookmarks.includes(activeKey)
                    ? bookmarks.filter((key) => key !== activeKey)
                    : [...bookmarks, activeKey];
                  persistBookmarks(next);
                }}
                icon={
                  activeKey && bookmarks.includes(activeKey) ? (
                    <BookmarkCheck className="size-3" aria-hidden />
                  ) : (
                    <Bookmark className="size-3" aria-hidden />
                  )
                }
              >
                {activeKey && bookmarks.includes(activeKey) ? '已加书签' : '书签本章'}
              </Button>
              {courseId ? (
                <Link
                  href={`/course/${encodeURIComponent(courseId)}/overview`}
                  className="inline-flex h-8 items-center rounded-[var(--radius-sm)] border border-border px-2.5 text-[11px] text-text hover:border-accent/50"
                >
                  回到课程
                </Link>
              ) : null}
            </div>

            {bookmarks.length > 0 && book.data ? (
              <Card className="space-y-1 p-2">
                <p className="text-[10px] uppercase tracking-wide text-text-dim">书签</p>
                <ul className="space-y-0.5">
                  {bookmarks.map((key) => {
                    const target = book.data?.chapters.find((item) => item.key === key);
                    return (
                      <li key={key}>
                        <button
                          type="button"
                          onClick={() => setChapterKey(key)}
                          className="w-full truncate text-left text-[11px] text-text-muted hover:text-accent"
                        >
                          · {target?.title ?? key}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </Card>
            ) : null}

            {book.data ? (
              <SearchPanel
                bookId={bookId}
                chapterKeys={book.data.chapters.map((item) => ({ key: item.key, title: item.title }))}
                onJump={(key) => setChapterKey(key)}
              />
            ) : null}

            {book.data?.quality && Object.keys(book.data.quality).length > 0 ? (
              <Card className="space-y-1 p-2">
                <p className="text-[10px] uppercase tracking-wide text-text-dim">书籍质量</p>
                <ul className="space-y-0.5">
                  {Object.entries(book.data.quality)
                    .slice(0, 6)
                    .map(([key, value]) => (
                      <li key={key} className="flex justify-between gap-2 text-[10px]">
                        <span className="truncate text-text-dim">{key}</span>
                        <span className="truncate text-text-muted">{String(value)}</span>
                      </li>
                    ))}
                </ul>
              </Card>
            ) : null}
          </aside>
        </div>

        {book.data && book.data.status !== 'ready' ? (
          <div className="border-t border-border bg-warn/10 px-4 py-1.5 text-center text-[11px] text-warn">
            <Badge tone="warn" className="mr-2">
              {book.data.status}
            </Badge>
            书籍仍在生成，已完成的章节可以先读；本页会自动刷新。
          </div>
        ) : null}
      </div>
    </>
  );
}
