'use client';

import { Coins, Database, Gauge } from 'lucide-react';

import { Card, CardHeader, Skeleton } from '@/components/ui/card';
import type { MetricsResponse } from '@/lib/api/types';
import { formatCount, formatUsd } from '@/lib/format';

function pickNumber(source: Record<string, unknown> | undefined, keys: string[]): number | null {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    const num = typeof value === 'number' ? value : Number(value);
    if (Number.isFinite(num)) return num;
  }
  return null;
}

/**
 * Cost panel — spec §7.2 settings.
 *
 * `GET /v1/metrics` returns four loose dictionaries; we surface the numbers we
 * know (tokens/usd/jobs/cache hit rate) and ignore the rest rather than printing
 * a raw JSON blob at the user.
 */
export function CostPanel({
  metrics,
  loading,
}: {
  metrics: MetricsResponse | undefined;
  loading: boolean;
}) {
  const jobs = metrics?.jobs;
  const cache = metrics?.cache;
  const providers = metrics?.providers;
  const learning = metrics?.learning;

  const totalUsd = pickNumber(providers, ['usd', 'cost_usd', 'total_usd']);
  const totalTokens = pickNumber(providers, ['tokens', 'total_tokens']);
  const jobCount = pickNumber(jobs, ['total', 'count']);
  const failed = pickNumber(jobs, ['failed', 'failed_count']);
  const hitRate = pickNumber(cache, ['hit_rate', 'hitRatio']);
  const cached = pickNumber(cache, ['hits', 'cache_hits']);
  const lessons = pickNumber(learning, ['lessons_completed', 'completed_lessons', 'lessons']);

  return (
    <Card id="cost">
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <Coins className="size-3.5 text-accent" aria-hidden />
            成本与用量
          </span>
        }
        subtitle="预算守卫会在单次调用前估算 prompt 规模，超限直接拒绝。"
      />
      {loading ? (
        <Skeleton className="h-20" />
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Metric label="累计花费" value={totalUsd != null ? formatUsd(totalUsd) : '—'} icon={<Coins className="size-3" aria-hidden />} />
          <Metric label="累计 tokens" value={totalTokens != null ? formatCount(totalTokens) : '—'} />
          <Metric label="任务总数" value={jobCount != null ? String(jobCount) : '—'} />
          <Metric label="失败任务" value={failed != null ? String(failed) : '—'} tone={failed ? 'warn' : 'normal'} />
          <Metric label="缓存命中率" value={hitRate != null ? `${Math.round(hitRate <= 1 ? hitRate * 100 : hitRate)}%` : '—'} />
          <Metric label="缓存命中次数" value={cached != null ? String(cached) : '—'} />
          <Metric label="已完成课时" value={lessons != null ? String(lessons) : '—'} icon={<Gauge className="size-3" aria-hidden />} />
        </div>
      )}
      <p className="mt-2 flex items-center gap-1 text-[10px] text-text-dim">
        <Database className="size-2.5" aria-hidden />
        命中缓存的课程（同 repo + commit）不会重复消耗 token。
      </p>
    </Card>
  );
}

function Metric({
  label,
  value,
  icon,
  tone = 'normal',
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
  tone?: 'normal' | 'warn';
}) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-border px-2.5 py-2">
      <p className="flex items-center gap-1 text-[10px] text-text-dim">
        {icon}
        {label}
      </p>
      <p className={`mt-0.5 text-sm ${tone === 'warn' ? 'text-warn' : 'text-text'}`}>{value}</p>
    </div>
  );
}
