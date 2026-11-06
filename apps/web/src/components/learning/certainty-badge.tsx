'use client';

import { FlaskConical, Quote, Sigma } from 'lucide-react';

import { Badge, type BadgeTone } from '@/components/ui/card';
import type { Certainty } from '@/lib/api/types';

/**
 * Certainty badges — spec §6.4 “Trace 的三种确定性”.
 *
 * A teaching product must never blur "this is in the source" with "we inferred
 * it statically" and "we are simulating execution". Every trace step and the
 * player carry one of these three labels, and `teaching_simulation` is visible
 * permanently (not only on hover).
 */
const CERTAINTY: Record<
  string,
  { label: string; short: string; tone: BadgeTone; description: string; icon: typeof Quote }
> = {
  source_fact: {
    label: '源码事实',
    short: 'fact',
    tone: 'accent',
    description: '有源码行作为证据，可以直接点开 file:line 核对。',
    icon: Quote,
  },
  static_inference: {
    label: '静态推断',
    short: 'infer',
    tone: 'info',
    description: '由静态分析（导入关系、类型、调用图）推断，未实际运行。',
    icon: Sigma,
  },
  teaching_simulation: {
    label: '教学模拟',
    short: 'sim',
    tone: 'warn',
    description: '为了让流程可读而构造的示例执行过程，变量值是示例值，不代表真实运行结果。',
    icon: FlaskConical,
  },
};

export function CertaintyBadge({
  certainty,
  showDescription = false,
}: {
  certainty: Certainty | string;
  showDescription?: boolean;
}) {
  const meta = CERTAINTY[certainty] ?? CERTAINTY.teaching_simulation!;
  const Icon = meta.icon;
  return (
    <span className="inline-flex flex-col gap-0.5">
      <Badge tone={meta.tone} title={meta.description}>
        <Icon className="size-2.5" aria-hidden />
        {meta.label}
      </Badge>
      {showDescription ? (
        <span className="text-[10px] leading-[1.5] text-text-dim">{meta.description}</span>
      ) : null}
    </span>
  );
}

/** Permanent "this is a simulation" strip required on the walkthrough layer. */
export function SimulationBanner({ note }: { note?: string }) {
  return (
    <div
      role="note"
      className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-warn/40 bg-warn/10 px-3 py-1.5 text-[11px] text-warn"
    >
      <FlaskConical className="size-3.5 shrink-0" aria-hidden />
      <span>
        本层包含<span className="font-semibold"> 教学模拟 · 教学推演 </span>
        内容：变量值是为了讲清流程构造的示例，不是真实运行结果。
        {note ? <span className="ml-1 text-text-muted">{note}</span> : null}
      </span>
    </div>
  );
}

export function certaintyLabel(certainty: Certainty | string): string {
  return CERTAINTY[certainty]?.label ?? '教学模拟';
}
