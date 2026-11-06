'use client';

import { AlertTriangle, CheckCircle2, CircleSlash, HelpCircle, Stethoscope } from 'lucide-react';

import { Badge, Card, CardHeader, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { DoctorCheck, DoctorStatus, HealthResponse } from '@/lib/api/types';

const STATUS_META: Record<DoctorStatus, { tone: 'accent' | 'warn' | 'danger' | 'muted'; icon: typeof CheckCircle2; label: string }> = {
  ok: { tone: 'accent', icon: CheckCircle2, label: '正常' },
  degraded: { tone: 'warn', icon: AlertTriangle, label: '降级' },
  fail: { tone: 'danger', icon: CircleSlash, label: '失败' },
  unknown: { tone: 'muted', icon: HelpCircle, label: '未知' },
};

/**
 * Doctor panel — spec §7.2 settings / §3.5.4 / §2.4.
 *
 * Shows the three Gate0 states (G1 依赖 / G2 内核 / G3 语音) plus DB / kernel /
 * TTS / GitHub checks from `GET /v1/settings/doctor`, and the raw `/healthz`
 * numbers so “启动成功但功能静默缺失” is impossible (§2.2 constraint 7).
 */
export function DoctorPanel({
  checks,
  loading,
  health,
  healthLoading,
  onRefresh,
  refreshing,
}: {
  checks: DoctorCheck[];
  loading: boolean;
  health: HealthResponse | undefined;
  healthLoading: boolean;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const gates = health?.gates ?? {};

  return (
    <Card id="doctor">
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <Stethoscope className="size-3.5 text-accent" aria-hidden />
            诊断面板
          </span>
        }
        subtitle="Gate 失败不会阻止启动，但会决定功能降级到什么程度。"
        action={
          <Button variant="ghost" size="sm" onClick={onRefresh} loading={refreshing}>
            重新检查
          </Button>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {(['g1', 'g2', 'g3'] as const).map((gate) => {
          const value = gates[gate] ?? 'unknown';
          const meta = STATUS_META[(value as DoctorStatus) in STATUS_META ? (value as DoctorStatus) : 'unknown'];
          return (
            <Badge key={gate} tone={meta.tone}>
              {gate.toUpperCase()} {value}
            </Badge>
          );
        })}
        {healthLoading ? <span className="text-[10px] text-text-dim">读取 /api/healthz…</span> : null}
        {health ? (
          <span className="ml-auto flex flex-wrap gap-1.5 text-[10px] text-text-dim">
            <span>db {health.db ? 'ok' : 'fail'}</span>
            <span>kernel {health.kernel ? 'ok' : 'fail'}</span>
            <span>migration {health.migration ? 'ok' : 'fail'}</span>
            <span className="font-mono">{health.version}</span>
          </span>
        ) : null}
      </div>

      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-8" />
          <Skeleton className="h-8" />
          <Skeleton className="h-8" />
        </div>
      ) : checks.length === 0 ? (
        <p className="text-[11px] text-text-dim">没有可用的检查项（后端可能还没实现 /settings/doctor）。</p>
      ) : (
        <ul className="divide-y divide-border overflow-hidden rounded-[var(--radius-sm)] border border-border">
          {checks.map((check) => {
            const meta = STATUS_META[check.status] ?? STATUS_META.unknown;
            const Icon = meta.icon;
            return (
              <li key={check.name} className="flex items-start gap-2 px-2.5 py-2">
                <Icon
                  className={`mt-0.5 size-3.5 shrink-0 ${
                    check.status === 'ok'
                      ? 'text-accent'
                      : check.status === 'fail'
                        ? 'text-danger'
                        : check.status === 'degraded'
                          ? 'text-warn'
                          : 'text-text-dim'
                  }`}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5 text-[11px] text-text">
                    <span className="truncate">{check.name}</span>
                    <span className="text-[10px] text-text-dim">{meta.label}</span>
                  </p>
                  {check.detail ? (
                    <p className="mt-0.5 text-[10px] leading-[1.55] text-text-muted">{check.detail}</p>
                  ) : null}
                  {check.hint ? (
                    <p className="mt-0.5 text-[10px] leading-[1.55] text-accent">{check.hint}</p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <p className="mt-2 text-[10px] leading-[1.6] text-text-dim">
        TTS 与 GitHub 检查失败时：课程仍可生成（字幕模式 / 匿名限流 60 次每小时），日志位置见
        <code className="mx-1 font-mono">var/logs/</code>。
      </p>
    </Card>
  );
}
