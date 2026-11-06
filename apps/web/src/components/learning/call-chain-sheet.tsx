'use client';

import { ArrowUpRight, Waypoints } from 'lucide-react';

import { Overlay } from '@/components/ui/overlay';
import { CertaintyBadge } from '@/components/learning/certainty-badge';
import type { EvidenceView, TraceStep } from '@/lib/api/types';
import { toEvidence } from '@/lib/api/types';

/**
 * Call-chain sheet — “查看调用链” from the walkthrough (spec §7.2).
 *
 * Vertical chain with one row per trace step: certainty, evidence and a jump
 * back to `file:line`. Rendered in an overlay so it never steals the code pane.
 */
export function CallChainSheet({
  open,
  onClose,
  steps,
  onJump,
}: {
  open: boolean;
  onClose: () => void;
  steps: TraceStep[];
  onJump: (evidence: EvidenceView) => void;
}) {
  return (
    <Overlay open={open} onClose={onClose} title="调用链" variant="sheet" description="从入口到输出的完整链路">
      {steps.length === 0 ? (
        <p className="text-[11px] text-text-dim">没有调用链数据。</p>
      ) : (
        <ol className="relative space-y-3 border-l border-border pl-4">
          {steps.map((step) => {
            const evidence = (step.evidence ?? [])
              .map(toEvidence)
              .filter((value): value is EvidenceView => Boolean(value));
            return (
              <li key={`${step.index}-${step.title}`} className="relative">
                <span
                  aria-hidden
                  className="absolute -left-[22px] top-1 grid size-3 place-items-center rounded-full border border-accent bg-bg"
                />
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-text">{step.title}</span>
                  <CertaintyBadge certainty={step.certainty} />
                </div>
                {step.variables.length > 0 ? (
                  <dl className="mt-1 space-y-0.5">
                    {step.variables.slice(0, 4).map((variable, index) => (
                      <div key={index} className="flex gap-2 font-mono text-[10px]">
                        <dt className="text-accent">{String(variable.name ?? '')}</dt>
                        <dd className="min-w-0 flex-1 truncate text-text-muted">
                          {String(variable.value ?? '')}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
                {evidence.length > 0 ? (
                  <ul className="mt-1 space-y-0.5">
                    {evidence.map((item, index) => (
                      <li key={`${item.file}-${index}`}>
                        <button
                          type="button"
                          onClick={() => {
                            onJump(item);
                            onClose();
                          }}
                          className="inline-flex items-center gap-0.5 font-mono text-[10px] text-info underline decoration-dotted underline-offset-2 hover:text-accent"
                        >
                          {item.file}:{item.line_start}
                          <ArrowUpRight className="size-2.5" aria-hidden />
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 flex items-center gap-1 text-[10px] text-warn">
                    <Waypoints className="size-2.5" aria-hidden />
                    无源码证据（教学模拟）
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Overlay>
  );
}
