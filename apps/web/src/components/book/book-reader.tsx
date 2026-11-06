'use client';

import Link from 'next/link';
import { Copy, ExternalLink, Minus, Plus, Sun } from 'lucide-react';
import { useState } from 'react';

import { Badge, Card, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Markdown } from '@/components/ui/markdown';
import { useToast } from '@/components/ui/toast';
import type { BookBlock, BookChapterDetail } from '@/lib/api/types';
import { readString, toEvidence, type EvidenceView } from '@/lib/api/types';
import { safeLocalStorageGet, safeLocalStorageSet, cn } from '@/lib/utils';

type BookTheme = 'dark' | 'sepia';

function useBookPreferences() {
  const [fontSize, setFontSize] = useState(() => {
    const stored = safeLocalStorageGet('rl_book_font_size');
    const parsed = stored ? Number.parseInt(stored, 10) : Number.NaN;
    return Number.isFinite(parsed) ? Math.min(22, Math.max(13, parsed)) : 15;
  });
  const [theme, setTheme] = useState<BookTheme>(() => {
    const stored = safeLocalStorageGet('rl_book_theme');
    return stored === 'sepia' ? 'sepia' : 'dark';
  });

  const updateFontSize = (value: number) => {
    const bounded = Math.min(22, Math.max(13, Math.round(value)));
    setFontSize(bounded);
    safeLocalStorageSet('rl_book_font_size', String(bounded));
  };
  const toggleTheme = () => {
    const next: BookTheme = theme === 'dark' ? 'sepia' : 'dark';
    setTheme(next);
    safeLocalStorageSet('rl_book_theme', next);
  };

  return { fontSize, updateFontSize, theme, toggleTheme };
}

function CodeBlock({
  block,
  sourceRef,
  courseId,
}: {
  block: BookBlock;
  sourceRef: EvidenceView | null;
  courseId: string | null;
}) {
  const toast = useToast();
  return (
    <div className="my-3 overflow-hidden rounded-[var(--radius-sm)] border border-border">
      <div className="flex items-center gap-2 border-b border-border bg-surface-2 px-2 py-1">
        <span className="font-mono text-[10px] text-text-dim">{block.lang ?? 'code'}</span>
        <span className="ml-auto flex items-center gap-1">
          {sourceRef && courseId ? (
            <Link
              href={`/course/${encodeURIComponent(courseId)}/deep-dive?file=${encodeURIComponent(sourceRef.file)}&line=${sourceRef.line_start}`}
              className="inline-flex items-center gap-1 text-[10px] text-accent hover:text-accent-strong"
            >
              <ExternalLink className="size-2.5" aria-hidden />
              在课程中查看此代码
            </Link>
          ) : null}
          <Button
            variant="ghost"
            size="sm"
            className="px-1.5"
            aria-label="复制代码"
            onClick={() => {
              void navigator.clipboard?.writeText(block.text ?? '');
              toast.push({ tone: 'success', title: '已复制代码' });
            }}
          >
            <Copy className="size-3" aria-hidden />
          </Button>
        </span>
      </div>
      <pre className="overflow-x-auto bg-code-bg p-3 font-mono text-[12px] leading-[1.55] text-text">
        {block.text}
      </pre>
      {block.caption ? <p className="border-t border-border px-2 py-1 text-[10px] text-text-dim">{block.caption}</p> : null}
    </div>
  );
}

export function BookReader({
  chapter,
  loading,
  courseId,
}: {
  chapter: BookChapterDetail | undefined;
  loading: boolean;
  courseId: string | null;
}) {
  const { fontSize, updateFontSize, theme, toggleTheme } = useBookPreferences();

  if (loading && !chapter) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-6 w-1/2" />
        <Skeleton className="h-4" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-32" />
      </div>
    );
  }

  if (!chapter) {
    return <p className="p-4 text-[11px] text-text-dim">选择一个章节开始阅读。</p>;
  }

  const sourceRefs = (chapter.source_refs ?? [])
    .map(toEvidence)
    .filter((value): value is EvidenceView => Boolean(value));

  return (
    <article
      className={cn(
        'mx-auto w-full max-w-[760px] px-5 py-6',
        theme === 'sepia' ? 'bg-[#1a1710]' : 'bg-transparent',
      )}
      style={{ fontSize: `${fontSize}px` }}
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h1 className="min-w-0 flex-1 text-[22px] font-semibold leading-snug text-text">{chapter.title}</h1>
        <span className="flex items-center gap-1">
          <Button variant="ghost" size="sm" className="px-1.5" aria-label="缩小字号" onClick={() => updateFontSize(fontSize - 1)}>
            <Minus className="size-3" aria-hidden />
          </Button>
          <span className="font-mono text-[10px] text-text-dim">{fontSize}</span>
          <Button variant="ghost" size="sm" className="px-1.5" aria-label="放大字号" onClick={() => updateFontSize(fontSize + 1)}>
            <Plus className="size-3" aria-hidden />
          </Button>
          <Button variant="ghost" size="sm" className="px-1.5" aria-label="切换主题" onClick={toggleTheme}>
            <Sun className="size-3" aria-hidden />
          </Button>
        </span>
      </div>

      {chapter.blocks.map((block, index) => {
        if (block.type === 'code') {
          const ref = sourceRefs[index] ?? sourceRefs[0] ?? null;
          return <CodeBlock key={index} block={block} sourceRef={ref} courseId={courseId} />;
        }
        if (block.type === 'figure') {
          return (
            <figure key={index} className="my-3">
              <div className="rounded-[var(--radius-sm)] border border-dashed border-border p-4 text-center text-[11px] text-text-dim">
                图示：{readString(block as unknown as Record<string, unknown>, 'caption') || '（本书中的示意图）'}
              </div>
              {block.caption ? <figcaption className="mt-1 text-center text-[10px] text-text-dim">{block.caption}</figcaption> : null}
            </figure>
          );
        }
        if (block.type === 'table') {
          return (
            <pre key={index} className="my-3 overflow-x-auto rounded-[var(--radius-sm)] border border-border bg-code-bg p-2 font-mono text-[11px] text-text-muted">
              {block.text}
            </pre>
          );
        }
        return (
          <Markdown key={index} className="my-3">
            {block.text ?? ''}
          </Markdown>
        );
      })}

      {sourceRefs.length > 0 ? (
        <Card className="mt-6 space-y-1">
          <p className="text-[10px] uppercase tracking-wide text-text-dim">本章源码出处</p>
          <ul className="space-y-0.5">
            {sourceRefs.slice(0, 8).map((ref, index) => (
              <li key={`${ref.file}-${index}`}>
                {courseId ? (
                  <Link
                    href={`/course/${encodeURIComponent(courseId)}/deep-dive?file=${encodeURIComponent(ref.file)}&line=${ref.line_start}`}
                    className="font-mono text-[10px] text-info underline decoration-dotted underline-offset-2 hover:text-accent"
                  >
                    {ref.file}:{ref.line_start}
                    {ref.line_end > ref.line_start ? `-${ref.line_end}` : ''}
                  </Link>
                ) : (
                  <span className="font-mono text-[10px] text-text-muted">
                    {ref.file}:{ref.line_start}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </article>
  );
}

export function BookStatusBadge({ status }: { status: string }) {
  const tone = status === 'ready' ? 'accent' : status === 'failed' ? 'danger' : 'warn';
  return <Badge tone={tone}>{status === 'ready' ? '可阅读' : status === 'failed' ? '生成失败' : '生成中'}</Badge>;
}
