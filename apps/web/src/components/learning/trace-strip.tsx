'use client';

import { ArrowRight, ListTree, Waypoints } from 'lucide-react';

import { Badge, Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { CertaintyBadge } from '@/components/learning/certainty-badge';
import type { EvidenceView, TraceStep } from '@/lib/api/types';
import { toEvidence } from '@/lib/api/types';
import { cn } from '@/lib/utils';

/**
 * TraceStrip — 4 horizontal steps of the guided walkthrough (spec §7.2 第二层).
 *
 * Switching steps cross-fades in 200ms and the current step carries its
 * certainty badge, so a "teaching simulation" step is never mistaken for a
 * verified source fact.
 */
export function TraceStrip({
  steps,
  currentIndex,
  onSelect,
  onOpenCallChain,
}: {
  steps: TraceStep[];
  currentIndex: number;
  onSelect: (index: number) => void;
  onOpenCallChain: () => void;
}) {
  if (steps.length === 0) {
    return (
      <Card className="flex items-center gap-2 text-[11px] text-text-dim">
        <Waypoints className="size-3.5" aria-hidden />
        本节没有调用链数据。
      </Card>
    );
  }

  return (
    <Card className="space-y-2">
      <div className="flex items-center gap-2">
        <ListTree className="size-3.5 text-accent" aria-hidden />
        <h3 className="text-xs font-semibold text-text">执行走读</h3>
        <span className="text-[10px] text-text-dim">
          {currentIndex + 1} / {steps.length}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto"
          onClick={onOpenCallChain}
          icon={<Waypoints className="size-3" aria-hidden />}
        >
          查看调用链
        </Button>
      </div>

      <ol className="flex gap-1.5 overflow-x-auto pb-1 rl-scroll-thin" aria-label="走读步骤">
        {steps.map((step, index) => {
          const active = index === currentIndex;
          const done = index < currentIndex;
          return (
            <li key={`${step.index}-${step.title}`} className="flex shrink-0 items-center gap-1.5">
              <button
                type="button"
                onClick={() => onSelect(index)}
                aria-current={active ? 'step' : undefined}
                className={cn(
                  'flex min-w-[124px] flex-col gap-1 rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-left transition-colors duration-200',
                  active
                    ? 'border-accent bg-accent-soft'
                    : done
                      ? 'border-accent/30 bg-surface text-text'
                      : 'border-border bg-surface-2/40 text-text-muted hover:border-border-strong',
                )}
              >
                <span className="flex items-center gap-1 text-[10px] text-text-dim">
                  <span
                    className={cn(
                      'grid size-4 place-items-center rounded-full border text-[9px]',
                      active ? 'border-accent text-accent' : 'border-border',
                    )}
                  >
                    {index + 1}
                  </span>
                  <CertaintyBadge certainty={step.certainty} />
                </span>
                <span className="truncate text-[11px] text-text">{step.title}</span>
              </button>
              {index < steps.length - 1 ? (
                <ArrowRight className="size-3 shrink-0 text-text-dim" aria-hidden />
              ) : null}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

export function VariablePanel({
  variables,
  certainty,
}: {
  variables: Array<Record<string, unknown>>;
  certainty?: string;
}) {
  if (variables.length === 0) return null;

  return (
    <Card className="space-y-2">
      <div className="flex items-center gap-1.5">
        <h3 className="text-xs font-semibold text-text">关键变量</h3>
        {certainty ? <CertaintyBadge certainty={certainty} /> : null}
      </div>
      <dl className="space-y-1.5">
        {variables.map((variable, index) => {
          const name = String(variable.name ?? `var${index + 1}`);
          const value = String(variable.value ?? '');
          const note = typeof variable.note === 'string' ? variable.note : null;
          return (
            <div key={`${name}-${index}`} className="rounded-[var(--radius-sm)] border border-border bg-code-bg px-2 py-1.5">
              <div className="flex items-baseline gap-2">
                <dt className="shrink-0 font-mono text-[11px] text-accent">{name}</dt>
                <dd className="min-w-0 flex-1 truncate font-mono text-[11px] text-text">{value || '—'}</dd>
              </div>
              {note ? <p className="mt-0.5 text-[10px] text-warn">{note}</p> : null}
            </div>
          );
        })}
      </dl>
      <p className="text-[10px] leading-[1.5] text-text-dim">
        标注“示例值”的变量来自教学模拟，不代表真实运行结果；其余来自静态推断或源码事实。
      </p>
    </Card>
  );
}

export function EvidenceList({
  evidence,
  onJump,
}: {
  evidence: Array<Record<string, unknown>>;
  onJump: (evidence: EvidenceView) => void;
}) {
  const items = evidence.map(toEvidence).filter((value): value is EvidenceView => Boolean(value));
  if (items.length === 0) return null;
  return (
    <ul className="space-y-1">
      {items.map((item, index) => (
        <li key={`${item.file}-${item.line_start}-${index}`}>
          <button
            type="button"
            onClick={() => onJump(item)}
            className="inline-flex items-center gap-1 font-mono text-[10px] text-info underline decoration-dotted underline-offset-2 hover:text-accent"
          >
            {item.file}:{item.line_start}
            {item.line_end > item.line_start ? `-${item.line_end}` : ''}
            {item.symbol ? <span className="text-text-dim"> · {item.symbol}</span> : null}
          </button>
        </li>
      ))}
    </ul>
  );
}

export function TraceStepDetail({
  step,
  onJump,
}: {
  step: TraceStep;
  onJump: (evidence: EvidenceView) => void;
}) {
  return (
    <div className="space-y-2 rounded-[var(--radius-sm)] border border-border bg-surface-2/40 p-3">
      <div className="flex items-center gap-2">
        <span className="grid size-5 place-items-center rounded-full bg-surface text-[10px] text-text-muted">
          {step.index + 1}
        </span>
        <h4 className="min-w-0 flex-1 truncate text-xs font-medium text-text">{step.title}</h4>
        <CertaintyBadge certainty={step.certainty} />
      </div>
      {step.note ? <p className="text-[11px] leading-[1.65] text-text-muted">{step.note}</p> : null}
      <VariablePanel variables={step.variables} certainty={step.certainty} />
      {step.evidence.length > 0 ? (
        <div className="space-y-1">
          <p className="text-[10px] text-text-dim">证据</p>
          <EvidenceList evidence={step.evidence} onJump={onJump} />
        </div>
      ) : (
        <p className="text-[10px] text-warn">
          这一步没有源码证据（因此被标注为教学模拟，不冒充源码事实）。
        </p>
      )}
      <Badge tone="muted">{step.certainty}</Badge>
    </div>
  );
}
