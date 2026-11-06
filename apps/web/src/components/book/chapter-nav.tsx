'use client';

import Link from 'next/link';
import { BookOpen, ChevronRight } from 'lucide-react';

import { Badge, Skeleton } from '@/components/ui/card';
import { Overlay } from '@/components/ui/overlay';
import type { BookDetail } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import { cn } from '@/lib/utils';

/**
 * Book table of contents.
 *
 * The *body* is extracted so the same markup serves both homes (§3.3.2 D31):
 *  · `≥lg` — the permanent 240px rail next to the text;
 *  · `<lg` — an `Overlay variant="sheet"` titled 「目录」.
 * A drawer that renders a *second*, slightly different list is how "the sidebar
 * and the drawer disagree" bugs start, so there is exactly one list here.
 */
export function ChapterNavBody({
  book,
  activeKey,
  onSelect,
  variant = 'rail',
}: {
  book: BookDetail | undefined;
  activeKey: string | null;
  onSelect: (key: string) => void;
  variant?: 'rail' | 'sheet';
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
    <nav aria-label="目录" className="flex h-full min-h-0 flex-col">
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
                // 触屏视口（<lg）命中区 ≥44（§3.3.1）；桌面保持既有密度
                data-rl-tap=""
                className={cn(
                  'flex w-full items-start gap-1.5 px-3 py-1.5 text-left transition-colors',
                  'max-lg:min-h-[var(--tap-target)]',
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
        <Link
          href={`/book/${encodeURIComponent(book.id)}/pdf`}
          className="text-accent underline underline-offset-2"
        >
          导出 PDF / 打印视图
        </Link>
      </div>
      {variant === 'sheet' ? null : (
        <p className="border-t border-border px-3 py-1.5 text-[10px] text-text-dim lg:hidden">
          窄屏下目录会收进抽屉；随时可以从正文上方的「目录」重新打开。
        </p>
      )}
    </nav>
  );
}

/** `≥lg` rail form (rendered inside the page's `<aside>`). */
export function ChapterNav({
  book,
  activeKey,
  onSelect,
}: {
  book: BookDetail | undefined;
  activeKey: string | null;
  onSelect: (key: string) => void;
}) {
  return <ChapterNavBody book={book} activeKey={activeKey} onSelect={onSelect} />;
}

/** `<lg` drawer form. Title matches the trigger so screen-reader users can pair them. */
export function ChapterNavSheet({
  open,
  onClose,
  book,
  activeKey,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  book: BookDetail | undefined;
  activeKey: string | null;
  onSelect: (key: string) => void;
}) {
  return (
    <Overlay open={open} onClose={onClose} title="目录" variant="sheet">
      <ChapterNavBody
        book={book}
        activeKey={activeKey}
        onSelect={(key) => {
          onSelect(key);
          onClose();
        }}
        variant="sheet"
      />
    </Overlay>
  );
}
