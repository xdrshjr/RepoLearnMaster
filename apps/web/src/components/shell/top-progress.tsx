'use client';

import Link from 'next/link';
import { Check } from 'lucide-react';

import { cn } from '@/lib/utils';

export type CourseLayer = 'overview' | 'walkthrough' | 'deep-dive' | 'recap';

export const LAYERS: Array<{ key: CourseLayer; index: number; label: string; hint: string }> = [
  { key: 'overview', index: 1, label: '宏观架构', hint: '这门课的整体形状' },
  { key: 'walkthrough', index: 2, label: '全局走读', hint: '一次请求的完整流程' },
  { key: 'deep-dive', index: 3, label: '深入源码', hint: '逐行读关键实现' },
  { key: 'recap', index: 4, label: '完课总结', hint: '复盘与书籍' },
];

/** Top three-segment progress (1-2-3-4) — spec §7.2. */
export function TopProgress({
  courseId,
  active,
  completed,
  percent = 0,
}: {
  courseId: string;
  active: CourseLayer;
  completed: Partial<Record<CourseLayer, boolean>>;
  percent?: number;
}) {
  return (
    <nav aria-label="课程层次" className="flex items-center gap-1">
      {LAYERS.map((layer, index) => {
        const isActive = layer.key === active;
        const isDone = completed[layer.key] ?? false;
        return (
          <div key={layer.key} className="flex items-center">
            {index > 0 ? (
              <span
                aria-hidden
                className={cn('mx-1 h-px w-4 sm:w-6', isDone || isActive ? 'bg-accent/60' : 'bg-border')}
              />
            ) : null}
            <Link
              href={`/course/${encodeURIComponent(courseId)}/${layer.key}`}
              aria-current={isActive ? 'page' : undefined}
              title={layer.hint}
              className={cn(
                'flex items-center gap-1.5 rounded-full border px-2 py-1 text-[11px] transition-colors',
                isActive
                  ? 'border-accent bg-accent-soft text-accent'
                  : isDone
                    ? 'border-accent/40 text-text'
                    : 'border-border text-text-muted hover:border-border-strong hover:text-text',
              )}
            >
              <span
                aria-hidden
                className={cn(
                  'grid size-4 place-items-center rounded-full border text-[9px]',
                  isActive
                    ? 'border-accent bg-accent text-[#06110c]'
                    : isDone
                      ? 'border-accent/60 text-accent'
                      : 'border-border',
                )}
              >
                {isDone && !isActive ? <Check className="size-2.5" aria-hidden /> : layer.index}
              </span>
              <span className="hidden sm:inline">{layer.label}</span>
            </Link>
          </div>
        );
      })}
      <span className="ml-2 hidden font-mono text-[10px] text-text-dim md:inline">{percent}%</span>
    </nav>
  );
}
