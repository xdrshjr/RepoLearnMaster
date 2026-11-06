'use client';

import Link from 'next/link';
import { Clock, GitBranch, Play, Star } from 'lucide-react';

import { Badge, EmptyState, SectionTitle, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useCourses } from '@/lib/api/hooks';
import type { CourseListItem } from '@/lib/api/types';
import { formatCount, formatMinutes, formatRelativeTime } from '@/lib/format';
import { courseRoute } from '@/lib/repo/parseRepoUrl';

const PALETTES: Record<string, string> = {
  mint: 'from-accent/25 to-transparent',
  violet: 'from-[#8b7bf7]/25 to-transparent',
  amber: 'from-warn/25 to-transparent',
  sky: 'from-info/25 to-transparent',
};

function statusTone(status: string): 'accent' | 'warn' | 'danger' | 'neutral' {
  if (status === 'ready') return 'accent';
  if (status === 'generating' || status === 'queued') return 'warn';
  if (status === 'failed' || status === 'failed_budget') return 'danger';
  return 'neutral';
}

const STATUS_LABEL: Record<string, string> = {
  ready: '可学习',
  generating: '生成中',
  queued: '排队中',
  partial: '部分可用',
  failed: '生成失败',
  failed_budget: '预算耗尽',
  cancelled: '已取消',
  stale: '待重建',
};

export function CourseCard({ course }: { course: CourseListItem }) {
  const palette = PALETTES[course.cover_palette] ?? PALETTES.mint;
  return (
    <article className="group relative overflow-hidden rounded-[var(--radius)] border border-border bg-surface transition-colors hover:border-border-strong">
      <div aria-hidden className={`h-16 bg-gradient-to-br ${palette}`} />
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-text">{course.repo.full_name}</h3>
            <p className="mt-1 line-clamp-2 min-h-8 text-xs leading-[1.6] text-text-muted">
              {course.title || course.repo.description || '课程已生成，进入第一层查看宏观架构。'}
            </p>
          </div>
          <Badge tone={statusTone(course.status)}>{STATUS_LABEL[course.status] ?? course.status}</Badge>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-text-dim">
          <span className="inline-flex items-center gap-1">
            <Star className="size-3" aria-hidden />
            {formatCount(course.repo.stars ?? 0)}
          </span>
          <span className="inline-flex items-center gap-1">
            <GitBranch className="size-3" aria-hidden />
            {course.lesson_count} 课时
          </span>
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3" aria-hidden />
            {formatMinutes(course.minutes)}
          </span>
          {course.quality?.degraded ? <Badge tone="warn">降级生成</Badge> : null}
        </div>

        <div className="mt-3 flex items-center justify-between">
          <span className="text-[11px] text-text-dim">{formatRelativeTime(course.updated_at)}更新</span>
          <Link
            href={courseRoute(course.id, 'overview')}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-surface-2 px-2.5 py-1.5 text-xs text-text transition-colors hover:bg-accent-soft hover:text-accent"
          >
            <Play className="size-3" aria-hidden />
            开始学习
          </Link>
        </div>
      </div>
    </article>
  );
}

export function HotCourses() {
  const { data, isLoading, isError, error, refetch } = useCourses({ status: 'ready', limit: 4 });

  return (
    <section aria-labelledby="hot-title" className="mx-auto mt-14 w-full max-w-[1040px] px-4">
      <SectionTitle hint="已生成并可直接学习">热门课程</SectionTitle>
      <h2 id="hot-title" className="sr-only">
        热门课程
      </h2>
      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-48" />
          ))}
        </div>
      ) : isError ? (
        <EmptyState
          title="暂时拿不到热门课程"
          description={error instanceof Error ? error.message : '服务暂时不可用。'}
          action={
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              重试
            </Button>
          }
        />
      ) : data && data.items.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {data.items.map((course) => (
            <CourseCard key={course.id} course={course} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="还没有课程"
          description="粘贴一个仓库地址试试：facebook/react、microsoft/autogen、fastapi/fastapi 都可以。"
        />
      )}
    </section>
  );
}

export function RecentLearning() {
  const { data, isLoading } = useCourses({ limit: 3 });

  if (isLoading) {
    return (
      <section className="mx-auto mt-12 w-full max-w-[1040px] px-4">
        <Skeleton className="h-24" />
      </section>
    );
  }

  const items = data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <section aria-labelledby="recent-title" className="mx-auto mt-12 w-full max-w-[1040px] px-4 pb-20">
      <SectionTitle hint="按最近更新排序">最近学习</SectionTitle>
      <h2 id="recent-title" className="sr-only">
        最近学习
      </h2>
      <ul className="divide-y divide-border overflow-hidden rounded-[var(--radius)] border border-border bg-surface">
        {items.map((course) => (
          <li key={course.id}>
            <Link
              href={courseRoute(course.id, 'overview')}
              className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-2"
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-[var(--radius-sm)] bg-accent-soft text-xs text-accent">
                {course.repo.full_name.slice(0, 2).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-text">{course.repo.full_name}</span>
                <span className="block truncate text-[11px] text-text-dim">
                  {course.title} · {course.lesson_count} 课时 · {formatMinutes(course.minutes)}
                </span>
              </span>
              <span className="shrink-0 text-[11px] text-text-dim">继续 →</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
