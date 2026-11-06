'use client';

import { useMemo } from 'react';

import { Badge } from '@/components/ui/card';
import { usePlayerStore } from '@/stores/player';
import { activeCue, cueProgress, cuesFromSegments } from '@/lib/player/subtitles';
import { cn } from '@/lib/utils';

/**
 * Subtitle view — spec §5.3 / §7.3.
 *
 * Reads the same store position as the transport bar and the code decorations;
 * it never runs its own timer. When the lesson has no audio the timing source is
 * `estimated` and the caption simply advances at 4.2 chars/second.
 */
export function SubtitleView({ className }: { className?: string }) {
  const captionsOn = usePlayerStore((state) => state.captionsOn);
  const stepIndex = usePlayerStore((state) => state.stepIndex);
  const positionMs = usePlayerStore((state) => state.positionMs);
  const timeline = usePlayerStore((state) => state.timeline);
  const status = usePlayerStore((state) => state.status);

  const step = timeline.steps[stepIndex];
  const cues = useMemo(() => (step ? cuesFromSegments(step.segments) : []), [step]);
  const cue = useMemo(() => activeCue(cues, positionMs), [cues, positionMs]);
  const progress = cue ? cueProgress(cue, positionMs) : 0;

  if (!captionsOn || !step) return null;

  return (
    <div
      className={cn(
        'border-t border-border bg-bg px-4 py-3',
        className,
      )}
      aria-live="polite"
      aria-atomic="true"
    >
      <div className="mx-auto max-w-[900px]">
        <div className="mb-1 flex items-center gap-2">
          <Badge tone={step.timingSource === 'tts' ? 'accent' : 'warn'}>
            {step.timingSource === 'tts' ? '配音 · 精确时间轴' : '本节暂无配音，已切换字幕模式'}
          </Badge>
          <span className="truncate text-[11px] text-text-dim">
            步骤 {stepIndex + 1} · {step.title}
          </span>
          {status === 'seeking' ? <Badge tone="info">定位中</Badge> : null}
        </div>

        <p className="min-h-[2.6em] text-[15px] leading-[1.65] text-text">
          {cue?.text || '（本节没有旁白文本，右侧 Momo 会讲解当前代码。）'}
        </p>

        <div className="mt-1.5 h-0.5 w-full overflow-hidden rounded-full bg-surface-2" aria-hidden>
          <div
            className="h-full rounded-full bg-accent/70 transition-[width] duration-150"
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
}
