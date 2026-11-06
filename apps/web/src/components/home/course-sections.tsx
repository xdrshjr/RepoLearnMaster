'use client';

import Link from 'next/link';
import { Clock, GitBranch, Play, SearchX, Star } from 'lucide-react';

import { Badge, EmptyState, SectionTitle, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useCourses, type CourseSearchResponse, type HighlightGroup, type HighlightSegment } from '@/lib/api/hooks';
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

/**
 * 高亮片段渲染（spec §3.4.4）。
 *
 * 服务端只回 `{text, marked}` 切段、**从不回 HTML**，所以这里用 React 元素逐个
 * 渲染；`<mark>` 由 React 生成，全仓因此不需要（也不允许）为搜索引入
 * `dangerouslySetInnerHTML`——`title`/`summary` 来自 LLM，注入面是真实存在的。
 */
export function HighlightedText({
  segments,
  fallback,
}: {
  segments?: HighlightSegment[] | null;
  fallback: React.ReactNode;
}) {
  if (!segments || segments.length === 0) return <>{fallback}</>;
  return (
    <>
      {segments.map((segment, index) =>
        segment.marked ? (
          <mark
            key={`${index}-${segment.text}`}
            className="rounded-[2px] bg-accent-soft px-0.5 text-accent"
          >
            {segment.text}
          </mark>
        ) : (
          segment.text
        ),
      )}
    </>
  );
}

export function CourseCard({
  course,
  highlights,
}: {
  course: CourseListItem;
  /** 搜索命中时才给：未搜索时服务端返回 null，卡片与原来逐字节一致 (§3.4.4)。 */
  highlights?: HighlightGroup | null;
}) {
  const palette = PALETTES[course.cover_palette] ?? PALETTES.mint;
  return (
    <article className="group relative overflow-hidden rounded-[var(--radius)] border border-border bg-surface transition-colors hover:border-border-strong">
      <div aria-hidden className={`h-16 bg-gradient-to-br ${palette}`} />
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-text">
              <HighlightedText segments={highlights?.repo} fallback={course.repo.full_name} />
            </h3>
            <p className="mt-1 line-clamp-2 min-h-8 text-xs leading-[1.6] text-text-muted">
              <HighlightedText
                segments={highlights?.title ?? highlights?.summary}
                fallback={course.title || course.repo.description || '课程已生成，进入第一层查看宏观架构。'}
              />
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

/* --------------------------------------------------------- search result slab */

/**
 * 搜索结果区（spec §4.3 #51「接搜索态」）。
 *
 * 三种状态各自有明确文案，因为它们对用户意味着不同的事：
 *  · 空结果 → "没有找到匹配的课程"（而不是留一片空白让人以为界面坏了）；
 *  · 回退   → "这次是按创建时间列出的"（**列表仍然有内容**，这是 §3.4.3 第 3 条
 *             要防的静默空结果：2 字查询在 trigram 下返回 0 行且不报错）；
 *  · 失败   → 可执行的重试。
 *
 * `role="status"` 放在这块区域上：计数行变化即播报，`aria-atomic="false"` 保证
 * 屏幕阅读器只读变化的摘要行，而不是把整页结果重念一遍。
 */
export function SearchResults({
  query,
  data,
  isLoading,
  isPlaceholderData = false,
  isError,
  errorMessage,
  onRetry,
}: {
  query: string;
  data?: CourseSearchResponse;
  isLoading: boolean;
  isPlaceholderData?: boolean;
  isError: boolean;
  errorMessage?: string | null;
  onRetry: () => void;
}) {
  const items = data?.items ?? [];
  const total = typeof data?.total === 'number' ? data.total : items.length;
  const shortQuery = data?.fallback_reason === 'query_too_short';
  const summary = isError
    ? '搜索失败'
    : isLoading && items.length === 0
      ? '正在搜索…'
      : `找到 ${total} 门课`;

  if (isError) {
    return (
      <div role="status" aria-live="polite" aria-atomic="false" data-rl-search-results="" className="mt-4">
        <EmptyState
          title="搜索失败"
          description={errorMessage || '服务暂时不可用，稍后再试。'}
          action={
            <Button variant="outline" size="sm" onClick={onRetry}>
              重试
            </Button>
          }
        />
      </div>
    );
  }

  if (isLoading && items.length === 0) {
    return (
      <div role="status" aria-live="polite" aria-atomic="false" data-rl-search-results="" className="mt-4">
        <p className="mb-2 text-[11px] text-text-dim">{summary}</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-40" />
          ))}
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div role="status" aria-live="polite" aria-atomic="false" data-rl-search-results="" className="mt-4">
        <EmptyState
          icon={<SearchX className="size-5" aria-hidden />}
          title={`没有找到匹配「${query}」的课程`}
          description="换一个更短的关键词（≥3 字才走全文索引），或者直接搜仓库名，例如 facebook/react。"
        />
      </div>
    );
  }

  return (
    <div role="status" aria-live="polite" aria-atomic="false" data-rl-search-results="" className="mt-4">
      <p className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-text-dim">
        <span>{summary}</span>
        {shortQuery ? (
          <span className="text-warn">「{query}」短于 3 字：这次是按创建时间列出的，并不代表没有匹配。</span>
        ) : null}
        {isPlaceholderData && isLoading ? <span className="text-text-dim">更新中…</span> : null}
        {typeof data?.next_offset === 'number' ? (
          <span className="text-text-dim">全文索引分页至第 {data.next_offset} 条（上限 200）</span>
        ) : null}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((course) => (
          <CourseCard key={course.id} course={course} highlights={course.highlights} />
        ))}
      </div>
    </div>
  );
}
