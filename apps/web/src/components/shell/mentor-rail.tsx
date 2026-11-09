'use client';

import { ArrowUpRight, Bot, MessageSquarePlus } from 'lucide-react';
import { useMemo } from 'react';

import { Badge, Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { CertaintyBadge } from '@/components/learning/certainty-badge';
import type { EvidenceView, PlaybackBundle, TraceStep } from '@/lib/api/types';
import { toEvidence } from '@/lib/api/types';
import { usePlayerStore } from '@/stores/player';
import { useIdeStore } from '@/stores/ide';
import { cn } from '@/lib/utils';

/**
 * Momo mentor rail — spec §7.2 / §7.6.
 *
 * `aria-live="polite"`: it announces the *summary* (step title) rather than the
 * whole narration, which is what makes it usable with a screen reader.
 */
export function MentorRail({
  playback,
  lessonTitle,
  onAsk,
  className,
}: {
  playback: PlaybackBundle | undefined;
  lessonTitle: string;
  onAsk: () => void;
  className?: string;
}) {
  const stepIndex = usePlayerStore((state) => state.stepIndex);
  const positionMs = usePlayerStore((state) => state.positionMs);
  const timeline = usePlayerStore((state) => state.timeline);
  const focus = useIdeStore((state) => state.focus);
  const openFile = useIdeStore((state) => state.openFile);

  const step = timeline.steps[stepIndex];
  const traceSteps: TraceStep[] = playback?.trace?.steps ?? [];

  // Pick the trace step that best matches the current narration position.
  const activeTrace = useMemo(() => {
    if (traceSteps.length === 0) return null;
    const ratio = step && step.durationMs > 0 ? positionMs / step.durationMs : 0;
    const index = Math.min(traceSteps.length - 1, Math.floor(ratio * traceSteps.length));
    return traceSteps[index] ?? null;
  }, [positionMs, step, traceSteps]);

  const evidence = (activeTrace?.evidence ?? [])
    .map(toEvidence)
    .filter((value): value is EvidenceView => Boolean(value))
    .slice(0, 4);

  const narration = step?.segments[0]?.text ?? '';

  return (
    <div className={cn('flex h-full min-h-0 flex-col border-l border-border bg-bg-elevated', className)}>
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span aria-hidden className="grid size-6 place-items-center rounded-full bg-accent-soft text-accent">
          <Bot className="size-3.5" />
        </span>
        <div className="min-w-0">
          <p className="text-[11px] font-semibold text-text">Momo · 领读</p>
          <p className="truncate text-[10px] text-text-dim">{lessonTitle}</p>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3 rl-scroll-thin">
        <div aria-live="polite" aria-atomic="true">
          <p className="text-[10px] uppercase tracking-wide text-text-dim">当前步骤</p>
          <p className="mt-1 text-xs font-medium text-text">
            步骤 {stepIndex + 1} · {step?.title ?? '—'}
          </p>
          {activeTrace ? (
            <div className="mt-1.5 flex items-center gap-1.5">
              <CertaintyBadge certainty={activeTrace.certainty} />
              <span className="truncate text-[10px] text-text-dim">{activeTrace.title}</span>
            </div>
          ) : null}
        </div>

        {narration ? (
          <Card className="space-y-1 p-2.5">
            <p className="text-[10px] text-text-dim">讲解摘要</p>
            <p className="text-[11px] leading-[1.65] text-text-muted">
              {narration.length > 140 ? `${narration.slice(0, 140)}…` : narration}
            </p>
          </Card>
        ) : null}

        {focus ? (
          <div className="space-y-1">
            <p className="text-[10px] text-text-dim">当前高亮（文字说明，不只靠颜色）</p>
            <button
              type="button"
              onClick={() => openFile(focus.file, focus)}
              className="w-full rounded-[var(--radius-sm)] border border-border bg-surface px-2 py-1.5 text-left font-mono text-[10px] text-text hover:border-accent/50"
            >
              {focus.file}:{focus.lineStart}
              {focus.lineEnd > focus.lineStart ? `-${focus.lineEnd}` : ''}
            </button>
          </div>
        ) : null}

        {evidence.length > 0 ? (
          <div className="space-y-1">
            <p className="text-[10px] text-text-dim">源码证据</p>
            <ul className="space-y-1">
              {evidence.map((item, index) => (
                <li key={`${item.file}-${index}`}>
                  <button
                    type="button"
                    onClick={() => openFile(item.file, { file: item.file, lineStart: item.line_start, lineEnd: item.line_end })}
                    className="inline-flex items-center gap-0.5 font-mono text-[10px] text-info underline decoration-dotted underline-offset-2 hover:text-accent"
                  >
                    {item.file}:{item.line_start}
                    <ArrowUpRight className="size-2.5" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {step?.timingSource === 'estimated' ? (
          <div className="space-y-1">
            <Badge tone="warn">本节无配音 · 字幕自动推进</Badge>
            {playback?.no_voice_reason ? (
              // 有 TTS 但没合成成功时，把真实原因显示出来：只说"无配音"会让用户
              // 分不清"我没配"和"配错了 / 网关不支持"（2026-11-09 实测踩到）。
              <p className="break-words text-[10px] leading-[1.5] text-text-dim" title={playback.no_voice_reason}>
                原因：{playback.no_voice_reason}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="border-t border-border p-2">
        <Button variant="primary" size="sm" block onClick={onAsk} icon={<MessageSquarePlus className="size-3.5" aria-hidden />}>
          选中代码问 Momo
        </Button>
      </div>
    </div>
  );
}
