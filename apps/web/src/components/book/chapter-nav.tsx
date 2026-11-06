'use client';

import Link from 'next/link';
import { BookOpen, ChevronRight } from 'lucide-react';

import { Badge, Skeleton } from '@/components/ui/card';
import type { BookDetail } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import { cn } from '@/lib/utils';

export function ChapterNav({
  book,
  activeKey,
  onSelect,
}: {
  book: BookDetail | undefined;
  activeKey: string | null;
  onSelect: (key: string) => void;
}) {
  if (!book) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton key={index} className="h-4" />
        ))}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-border px-3 py-2">
        <p className="flex items-center gap-1.5 text-[11px] font-semibold text-text">
          <BookOpen className="size-3.5 text-accent" aria-hidden />
          目录
        </p>
        <p className="mt-0.5 text-[10px] text-text-dim">
          {book.chapters.length} 章 · {formatCount(book.word_count)} 字 · {book.preset}
        </p>
        {book.status !== 'ready' ? (
          <Badge tone="warn" className="mt-1">
            {book.status === 'generating' ? '生成中' : book.status}
          </Badge>
        ) : null}
      </div>
      <ol className="min-h-0 flex-1 overflow-y-auto py-1 rl-scroll-thin">
        {book.chapters.map((chapter, index) => {
          const active = chapter.key === activeKey;
          return (
            <li key={chapter.key}>
              <button
                type="button"
                onClick={() => onSelect(chapter.key)}
                aria-current={active ? 'true' : undefined}
                className={cn(
                  'flex w-full items-start gap-1.5 px-3 py-1.5 text-left transition-colors',
                  active ? 'bg-accent-soft text-accent' : 'text-text-muted hover:bg-surface-2 hover:text-text',
                )}
              >
                <ChevronRight
                  className={cn('mt-0.5 size-3 shrink-0', active ? 'text-accent' : 'text-text-dim')}
                  aria-hidden
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[11px]">
                    {index + 1}. {chapter.title}
                  </span>
                  <span className="block text-[10px] text-text-dim">{formatCount(chapter.words)} 字</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <div className="border-t border-border px-3 py-2 text-[10px] text-text-dim">
        <Link href={`/book/${encodeURIComponent(book.id)}/pdf`} className="text-accent underline underline-offset-2">
          导出 PDF / 打印视图
        </Link>
      </div>
    </div>
  );
}
