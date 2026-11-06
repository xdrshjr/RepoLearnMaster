'use client';

import { AlertCircle, Check, Loader2 } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { PREPARE_SECTIONS, type PrepareState, type SectionState } from '@/lib/jobs/prepare-state';
import { cn } from '@/lib/utils';

function SectionIcon({ state }: { state: SectionState }) {
  if (state === 'done') return <Check className="size-3.5" aria-hidden />;
  if (state === 'active') return <Loader2 className="size-3.5 animate-spin" aria-hidden />;
  if (state === 'failed') return <AlertCircle className="size-3.5" aria-hidden />;
  return <span aria-hidden className="block size-1.5 rounded-full bg-current" />;
}

const STATE_STYLE: Record<SectionState, string> = {
  pending: 'border-border bg-surface-2/40 text-text-dim',
  active: 'border-accent/60 bg-accent-soft text-accent',
  done: 'border-accent/40 bg-surface text-text',
  failed: 'border-danger/50 bg-danger/10 text-danger',
};

const STATE_LABEL: Record<SectionState, string> = {
  pending: '等待中',
  active: '进行中',
  done: '已完成',
  failed: '失败',
};

export function PrepareProgress({
  state,
  sseStatus,
  jobStatus,
  cost,
  onCancel,
  cancelling,
}: {
  state: PrepareState;
  sseStatus: string;
  jobStatus?: string;
  cost?: { tokens: number; usd: number };
  onCancel?: () => void;
  cancelling?: boolean;
}) {
  const doneCount = state.sections.filter((value) => value === 'done').length;

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-text">生成进度</h2>
          <p className="mt-0.5 text-[11px] text-text-muted">
            {state.completed
              ? '四段全部完成，可以开始学习了。'
              : `${doneCount} / 4 段完成 · ${state.message ?? '正在启动生成流程'}`}
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-text-dim">
          <span
            className={cn(
              'inline-flex items-center gap-1 rounded-full border px-2 py-0.5',
              sseStatus === 'open'
                ? 'border-accent/40 text-accent'
                : sseStatus === 'error'
                  ? 'border-danger/40 text-danger'
                  : 'border-border text-text-dim',
            )}
          >
            <span
              aria-hidden
              className={cn(
                'size-1.5 rounded-full',
                sseStatus === 'open' ? 'bg-accent' : sseStatus === 'error' ? 'bg-danger' : 'bg-text-dim',
              )}
            />
            {sseStatus === 'open' ? '实时连接' : sseStatus === 'error' ? '连接已断开' : '连接中'}
          </span>
          {cost ? (
            <span>
              {cost.tokens.toLocaleString()} tokens · ${cost.usd.toFixed(3)}
            </span>
          ) : null}
          {onCancel && !state.completed && jobStatus !== 'failed' ? (
            <Button variant="ghost" size="sm" onClick={onCancel} loading={cancelling}>
              取消
            </Button>
          ) : null}
        </div>
      </div>

      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
        role="progressbar"
        aria-valuenow={Math.round(state.progress)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="课程生成进度"
      >
        <div
          className={cn(
            'h-full rounded-full transition-[width] duration-500',
            state.error ? 'bg-danger' : 'bg-accent',
          )}
          style={{ width: `${Math.max(2, state.progress)}%` }}
        />
      </div>

      <ol className="grid gap-2 sm:grid-cols-2">
        {PREPARE_SECTIONS.map((section, index) => {
          const sectionState = state.sections[index] ?? 'pending';
          return (
            <li
              key={section.key}
              className={cn('rounded-[var(--radius-sm)] border px-3 py-2 transition-colors', STATE_STYLE[sectionState])}
              aria-current={sectionState === 'active' ? 'step' : undefined}
            >
              <div className="flex items-center gap-1.5">
                <SectionIcon state={sectionState} />
                <span className="text-xs font-medium">{section.title}</span>
                <span className="ml-auto text-[10px]">{STATE_LABEL[sectionState]}</span>
              </div>
              <p className="mt-1 text-[11px] leading-[1.55] text-text-dim">{section.description}</p>
            </li>
          );
        })}
      </ol>

      {state.warnings.length > 0 ? (
        <div className="rounded-[var(--radius-sm)] border border-warn/40 bg-warn/5 px-3 py-2">
          <p className="text-[11px] font-medium text-warn">生成过程中的告警</p>
          <ul className="mt-1 space-y-1">
            {state.warnings.slice(-6).map((warning, index) => (
              <li key={`${warning.node}-${index}`} className="text-[11px] text-text-muted">
                <span className="font-mono text-text-dim">{warning.node}</span>：{warning.warnings.join('；')}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}
