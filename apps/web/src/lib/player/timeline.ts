/**
 * Timeline math — spec §7.3 / §3.8.
 *
 * Pure functions only (no React, no DOM) so they can be unit tested and so the
 * player has exactly ONE time source: subtitles, code highlight and board
 * actions are all derived by asking this module "what is true at t".
 *
 * Rules encoded here:
 *  - `segments` are sorted by `start_ms`; locating a segment is a binary search;
 *  - the timeline is total: `t = 0` → first segment, `t = duration` → last one;
 *  - no audio (`audio === null`) → estimated advance at 4.2 chars/second;
 *  - speed only changes `playbackRate`, never the timeline itself.
 */

import type { FocusRef, PlaybackBundle, Segment, StepBundle } from '@/lib/api/types';

/** Characters per second used for the no-audio estimate (§3.8). */
export const CHARS_PER_SECOND = 4.2;

export const SPEED_OPTIONS = [0.75, 1, 1.25, 1.5, 2] as const;
export type PlaybackSpeed = (typeof SPEED_OPTIONS)[number];

export interface TimelineSegment {
  id: string;
  text: string;
  startMs: number;
  endMs: number;
  focus: FocusRef | null;
  subtitleStyle: string;
  boardActions: Array<Record<string, unknown>>;
}

export interface StepTimeline {
  index: number;
  title: string;
  durationMs: number;
  timingSource: 'tts' | 'estimated';
  audioUrl: string | null;
  segments: TimelineSegment[];
  codeNotes: StepBundle['code_notes'];
  quiz: StepBundle['quiz'];
  board: StepBundle['board'];
}

export interface CourseTimeline {
  steps: StepTimeline[];
  /** Absolute start offset (ms) of each step within the lesson. */
  offsets: number[];
  totalMs: number;
}

/** 4.2 chars/second → ms, rounded up so a subtitle never ends before its text. */
export function estimateDurationMs(text: string): number {
  if (!text) return 0;
  return Math.ceil((text.length / CHARS_PER_SECOND) * 1000);
}

export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(Math.max(value, min), max);
}

function toTimelineSegment(segment: Segment): TimelineSegment {
  return {
    id: segment.id,
    text: segment.text,
    startMs: Math.max(0, Math.round(segment.start_ms)),
    endMs: Math.max(0, Math.round(segment.end_ms)),
    focus: segment.focus ?? null,
    subtitleStyle: segment.subtitle_style ?? 'normal',
    boardActions: segment.board_actions ?? [],
  };
}

/**
 * Normalises a step's segments:
 *  - sorted by start (server guarantees it, but a bad bundle must not break the
 *    player);
 *  - a zero/absent `end_ms` is derived from the text estimate;
 *  - the run is stretched to cover `[0, durationMs]` so no `t` falls in a hole.
 */
export function normalizeSegments(raw: Segment[], durationMs: number): TimelineSegment[] {
  const segments = raw.map(toTimelineSegment).sort((a, b) => a.startMs - b.startMs);
  if (segments.length === 0) {
    return [
      {
        id: 's0',
        text: '',
        startMs: 0,
        endMs: Math.max(0, durationMs),
        focus: null,
        subtitleStyle: 'normal',
        boardActions: [],
      },
    ];
  }

  for (let i = 0; i < segments.length; i += 1) {
    const current = segments[i]!;
    if (current.endMs <= current.startMs) {
      current.endMs = current.startMs + Math.max(estimateDurationMs(current.text), 400);
    }
    const next = segments[i + 1];
    if (next && current.endMs > next.startMs) {
      // Never leave overlaps: the earlier segment yields to the later one.
      current.endMs = next.startMs;
    }
  }

  const first = segments[0]!;
  if (first.startMs > 0) first.startMs = 0;
  const last = segments[segments.length - 1]!;
  if (durationMs > 0 && last.endMs < durationMs) last.endMs = durationMs;
  if (durationMs > 0 && last.endMs > durationMs) last.endMs = durationMs;

  return segments;
}

export function stepDurationMs(step: StepBundle): number {
  const audioMs = step.audio?.duration_ms ?? 0;
  const declared = Number.isFinite(step.duration_ms) ? step.duration_ms : 0;
  if (audioMs > 0) return audioMs;
  if (declared > 0) return declared;
  const estimated = step.segments.reduce(
    (sum, segment) => sum + Math.max(estimateDurationMs(segment.text), 400),
    0,
  );
  return estimated > 0 ? estimated : 1000;
}

export function buildStepTimeline(step: StepBundle): StepTimeline {
  const durationMs = stepDurationMs(step);
  const hasAudio = Boolean(step.audio?.url);
  return {
    index: step.index,
    title: step.title,
    durationMs,
    timingSource: hasAudio ? 'tts' : 'estimated',
    audioUrl: hasAudio ? (step.audio?.url ?? null) : null,
    segments: normalizeSegments(step.segments ?? [], durationMs),
    codeNotes: step.code_notes ?? [],
    quiz: step.quiz ?? [],
    board: step.board ?? null,
  };
}

export function buildCourseTimeline(bundle: PlaybackBundle | null): CourseTimeline {
  if (!bundle || bundle.steps.length === 0) {
    return { steps: [], offsets: [], totalMs: 0 };
  }
  const steps = bundle.steps.map(buildStepTimeline);
  const offsets: number[] = [];
  let cursor = 0;
  for (const step of steps) {
    offsets.push(cursor);
    cursor += step.durationMs;
  }
  return { steps, offsets, totalMs: cursor };
}

/**
 * Binary search for the segment containing `ms`.
 * Always returns a valid index for a non-empty list (boundary-safe).
 */
export function findSegmentIndex(segments: TimelineSegment[], ms: number): number {
  if (segments.length === 0) return -1;
  const first = segments[0]!;
  if (ms <= first.startMs) return 0;
  const lastIndex = segments.length - 1;
  const last = segments[lastIndex]!;
  if (ms >= last.endMs) return lastIndex;

  let low = 0;
  let high = lastIndex;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const segment = segments[mid]!;
    if (ms < segment.startMs) {
      high = mid - 1;
    } else if (ms >= segment.endMs) {
      low = mid + 1;
    } else {
      return mid;
    }
  }
  // `ms` fell into a gap between two segments: attribute it to the earlier one.
  return Math.min(Math.max(high, 0), lastIndex);
}

export function segmentAt(segments: TimelineSegment[], ms: number): TimelineSegment | null {
  const index = findSegmentIndex(segments, ms);
  return index === -1 ? null : (segments[index] ?? null);
}

/** Index of the step containing `globalMs` (binary search over offsets). */
export function findStepIndex(timeline: CourseTimeline, globalMs: number): number {
  const { offsets, steps } = timeline;
  if (steps.length === 0) return -1;
  if (globalMs <= 0) return 0;
  const lastIndex = steps.length - 1;
  if (globalMs >= timeline.totalMs) return lastIndex;

  let low = 0;
  let high = lastIndex;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const offset = offsets[mid]!;
    const end = offset + steps[mid]!.durationMs;
    if (globalMs < offset) high = mid - 1;
    else if (globalMs >= end) low = mid + 1;
    else return mid;
  }
  return Math.min(Math.max(high, 0), lastIndex);
}

export interface TimelineLocation {
  stepIndex: number;
  step: StepTimeline | null;
  segmentIndex: number;
  segment: TimelineSegment | null;
  /** Position inside the current step. */
  stepPositionMs: number;
  /** Position inside the whole lesson. */
  globalPositionMs: number;
}

export function locate(timeline: CourseTimeline, globalMs: number): TimelineLocation {
  const stepIndex = findStepIndex(timeline, globalMs);
  if (stepIndex === -1) {
    return {
      stepIndex: -1,
      step: null,
      segmentIndex: -1,
      segment: null,
      stepPositionMs: 0,
      globalPositionMs: 0,
    };
  }
  const step = timeline.steps[stepIndex]!;
  const offset = timeline.offsets[stepIndex] ?? 0;
  const stepPositionMs = clamp(globalMs - offset, 0, step.durationMs);
  const segmentIndex = findSegmentIndex(step.segments, stepPositionMs);
  return {
    stepIndex,
    step,
    segmentIndex,
    segment: segmentIndex === -1 ? null : (step.segments[segmentIndex] ?? null),
    stepPositionMs,
    globalPositionMs: offset + stepPositionMs,
  };
}

export function globalPositionOf(timeline: CourseTimeline, stepIndex: number, stepMs: number): number {
  const offset = timeline.offsets[stepIndex] ?? 0;
  const step = timeline.steps[stepIndex];
  const bounded = step ? clamp(stepMs, 0, step.durationMs) : Math.max(0, stepMs);
  return offset + bounded;
}

/** Progress percent inside one step, for the transport bar. */
export function stepProgress(step: StepTimeline, positionMs: number): number {
  if (step.durationMs <= 0) return 0;
  return clamp(positionMs / step.durationMs, 0, 1);
}

export function formatClock(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

/**
 * Estimated-advance mode: with no audio the position advances by wall-clock
 * elapsed × speed. 4.2 chars/s is already baked into the segment durations, so
 * speed is the only multiplier.
 */
export function advanceEstimated(positionMs: number, elapsedMs: number, speed: number): number {
  return positionMs + elapsedMs * speed;
}

export function nextSpeed(speed: number): PlaybackSpeed {
  const index = SPEED_OPTIONS.indexOf(speed as PlaybackSpeed);
  if (index === -1) return 1;
  return SPEED_OPTIONS[(index + 1) % SPEED_OPTIONS.length] ?? 1;
}

export function previousSpeed(speed: number): PlaybackSpeed {
  const index = SPEED_OPTIONS.indexOf(speed as PlaybackSpeed);
  if (index === -1) return 1;
  return SPEED_OPTIONS[(index - 1 + SPEED_OPTIONS.length) % SPEED_OPTIONS.length] ?? 1;
}
