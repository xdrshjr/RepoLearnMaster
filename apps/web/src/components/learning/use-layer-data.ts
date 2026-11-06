'use client';

import { useEffect, useMemo, useRef } from 'react';

import { useIdeStore } from '@/stores/ide';
import { usePlayerStore } from '@/stores/player';
import { findSegmentIndex } from '@/lib/player/timeline';
import type { EvidenceView, TraceStep } from '@/lib/api/types';
import { toEvidence } from '@/lib/api/types';

/**
 * Couples narration to the IDE.
 *
 * Decorations are only recomputed when the *segment* changes, never every frame
 * (§7.3 rule 2: rebuilding Monaco decorations at 60fps is what makes these
 * pages feel broken).
 */
export function useSyncFocus(): void {
  const stepIndex = usePlayerStore((state) => state.stepIndex);
  const positionMs = usePlayerStore((state) => state.positionMs);
  const timeline = usePlayerStore((state) => state.timeline);
  const openFile = useIdeStore((state) => state.openFile);
  const lastSegment = useRef<string | null>(null);

  useEffect(() => {
    const step = timeline.steps[stepIndex];
    if (!step) return;
    const index = findSegmentIndex(step.segments, positionMs);
    const segment = index === -1 ? null : step.segments[index];
    if (!segment || !segment.focus) return;
    if (lastSegment.current === segment.id) return;
    lastSegment.current = segment.id;
    openFile(
      segment.focus.file,
      {
        file: segment.focus.file,
        lineStart: segment.focus.line_start,
        lineEnd: segment.focus.line_end,
      },
      // Narration-driven jumps are not user navigation: keep the back-stack clean.
      { remember: false },
    );
  }, [stepIndex, positionMs, timeline, openFile]);
}

/** Per-layer aggregate: notes, quizzes and the trace step active right now. */
export function useLayerData() {
  const timeline = usePlayerStore((state) => state.timeline);
  const stepIndex = usePlayerStore((state) => state.stepIndex);
  const positionMs = usePlayerStore((state) => state.positionMs);

  return useMemo(() => {
    const step = timeline.steps[stepIndex];
    const codeNotes = timeline.steps.flatMap((item) => item.codeNotes);
    const quiz = timeline.steps.flatMap((item) => item.quiz);
    const segments = step?.segments ?? [];
    const index = findSegmentIndex(segments, positionMs);
    const segment = index === -1 ? null : segments[index] ?? null;
    return { step, codeNotes, quiz, segment };
  }, [timeline, stepIndex, positionMs]);
}

/** Evidence of the trace step that matches the current narration position. */
export function activeTraceStep(steps: TraceStep[], ratio: number): TraceStep | null {
  if (steps.length === 0) return null;
  const index = Math.min(steps.length - 1, Math.max(0, Math.floor(ratio * steps.length)));
  return steps[index] ?? null;
}

export function evidenceToAnchor(evidence: EvidenceView): { file: string; lineStart: number; lineEnd: number } {
  return { file: evidence.file, lineStart: evidence.line_start, lineEnd: evidence.line_end };
}

export function evidenceViews(step: TraceStep | null): EvidenceView[] {
  if (!step) return [];
  return (step.evidence ?? [])
    .map(toEvidence)
    .filter((value): value is EvidenceView => Boolean(value));
}
