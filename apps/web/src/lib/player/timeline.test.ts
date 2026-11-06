import { describe, expect, it } from 'vitest';

import type { PlaybackBundle, StepBundle } from '@/lib/api/types';
import {
  advanceEstimated,
  buildCourseTimeline,
  buildStepTimeline,
  CHARS_PER_SECOND,
  estimateDurationMs,
  findSegmentIndex,
  findStepIndex,
  formatClock,
  globalPositionOf,
  locate,
  nextSpeed,
  normalizeSegments,
  stepDurationMs,
  type TimelineSegment,
} from '@/lib/player/timeline';

function segment(id: string, start: number, end: number, text = id): TimelineSegment {
  return {
    id,
    text,
    startMs: start,
    endMs: end,
    focus: null,
    subtitleStyle: 'normal',
    boardActions: [],
  };
}

function step(overrides: Partial<StepBundle> = {}): StepBundle {
  return {
    index: 0,
    title: '步骤',
    duration_ms: 10_000,
    timing_source: 'tts',
    audio: { url: '/api/objects/audio/aa/a.mp3', duration_ms: 10_000, voice: 'zh' },
    segments: [],
    board: null,
    code_notes: [],
    quiz: [],
    certainty_legend: {},
    ...overrides,
  };
}

describe('timeline segment lookup', () => {
  const segments = [segment('a', 0, 3000), segment('b', 3000, 7000), segment('c', 7000, 10000)];

  it('locates every interior time to exactly one segment', () => {
    expect(findSegmentIndex(segments, 1)).toBe(0);
    expect(findSegmentIndex(segments, 2999)).toBe(0);
    expect(findSegmentIndex(segments, 3000)).toBe(1);
    expect(findSegmentIndex(segments, 6999)).toBe(1);
    expect(findSegmentIndex(segments, 7000)).toBe(2);
  });

  it('is boundary-safe at t=0 and t=duration', () => {
    expect(findSegmentIndex(segments, 0)).toBe(0);
    expect(findSegmentIndex(segments, 10_000)).toBe(2);
    expect(findSegmentIndex(segments, 99_999)).toBe(2);
    expect(findSegmentIndex(segments, -50)).toBe(0);
  });

  it('never returns an index outside the list', () => {
    for (let t = -100; t <= 10_500; t += 137) {
      const index = findSegmentIndex(segments, t);
      expect(index).toBeGreaterThanOrEqual(0);
      expect(index).toBeLessThan(segments.length);
    }
  });
});

describe('segment normalization', () => {
  it('stretches the last segment to cover the full duration', () => {
    const normalized = normalizeSegments(
      [
        { id: 's0', text: '第一段', start_ms: 0, end_ms: 2000, board_actions: [], subtitle_style: 'normal' },
        { id: 's1', text: '第二段', start_ms: 2000, end_ms: 4000, board_actions: [], subtitle_style: 'normal' },
      ],
      8000,
    );
    expect(normalized[1]?.endMs).toBe(8000);
  });

  it('derives a missing end from the 4.2 chars/second estimate', () => {
    const text = '这是一句测试字幕';
    const normalized = normalizeSegments(
      [{ id: 's0', text, start_ms: 0, end_ms: 0, board_actions: [], subtitle_style: 'normal' }],
      0,
    );
    expect(normalized[0]?.endMs).toBeGreaterThanOrEqual(estimateDurationMs(text));
  });

  it('creates a single synthetic segment when the bundle ships none', () => {
    const normalized = normalizeSegments([], 5000);
    expect(normalized).toHaveLength(1);
    expect(normalized[0]?.endMs).toBe(5000);
  });

  it('removes overlaps by yielding to the later segment', () => {
    const normalized = normalizeSegments(
      [
        { id: 's0', text: 'a', start_ms: 0, end_ms: 6000, board_actions: [], subtitle_style: 'normal' },
        { id: 's1', text: 'b', start_ms: 4000, end_ms: 9000, board_actions: [], subtitle_style: 'normal' },
      ],
      9000,
    );
    expect(normalized[0]?.endMs).toBe(4000);
  });
});

describe('estimated advance (no audio)', () => {
  it('uses 4.2 chars/second and scales with playback speed', () => {
    expect(CHARS_PER_SECOND).toBe(4.2);
    expect(estimateDurationMs('a'.repeat(42))).toBe(10_000);
    const start = buildStepTimeline(step({ audio: null, duration_ms: 0, segments: [] , timing_source: 'estimated' }));
    expect(start.timingSource).toBe('estimated');
    expect(start.audioUrl).toBeNull();
    expect(advanceEstimated(1000, 500, 1)).toBe(1500);
    // speed 2 advances twice as fast but never rewrites the timeline
    expect(advanceEstimated(1000, 500, 2)).toBe(2000);
  });

  it('falls back to the sum of segment estimates when duration is absent', () => {
    const text = 'a'.repeat(42);
    const duration = stepDurationMs(
      step({
        audio: null,
        duration_ms: 0,
        timing_source: 'estimated',
        segments: [
          { id: 's0', text, start_ms: 0, end_ms: 0, board_actions: [], subtitle_style: 'normal' },
        ],
      }),
    );
    expect(duration).toBe(10_000);
  });
});

describe('course timeline', () => {
  const bundle: PlaybackBundle = {
    course_id: 'crs_1',
    commit_sha: 'abc',
    lesson: { key: '1.1', title: '总体架构', layer: 'overview', minutes: 3 },
    files: [],
    trace: null,
    steps: [
      step({
        index: 0,
        duration_ms: 10_000,
        segments: [
          { id: 's0', text: 'a', start_ms: 0, end_ms: 5000, board_actions: [], subtitle_style: 'normal' },
          { id: 's1', text: 'b', start_ms: 5000, end_ms: 10_000, board_actions: [], subtitle_style: 'normal' },
        ],
      }),
      step({ index: 1, duration_ms: 5000, audio: { url: '/x.mp3', duration_ms: 5000, voice: 'zh' } }),
      step({ index: 2, duration_ms: 6000, audio: null }),
    ],
  };
  const timeline = buildCourseTimeline(bundle);

  it('computes offsets and total duration', () => {
    expect(timeline.offsets).toEqual([0, 10_000, 15_000]);
    expect(timeline.totalMs).toBe(21_000);
  });

  it('locates the right step for any global time', () => {
    expect(findStepIndex(timeline, 0)).toBe(0);
    expect(findStepIndex(timeline, 9_999)).toBe(0);
    expect(findStepIndex(timeline, 10_000)).toBe(1);
    expect(findStepIndex(timeline, 14_999)).toBe(1);
    expect(findStepIndex(timeline, 15_000)).toBe(2);
    expect(findStepIndex(timeline, 21_000)).toBe(2);
  });

  it('resolves step, segment and both positions at t=0', () => {
    const location = locate(timeline, 0);
    expect(location.stepIndex).toBe(0);
    expect(location.segmentIndex).toBe(0);
    expect(location.stepPositionMs).toBe(0);
    expect(location.globalPositionMs).toBe(0);
  });

  it('resolves the last segment at t=duration', () => {
    const location = locate(timeline, timeline.totalMs);
    expect(location.stepIndex).toBe(2);
    expect(location.stepPositionMs).toBe(6000);
    expect(location.segment?.id).toBe('s0');
  });

  it('treats positions beyond the end as the end (ended state)', () => {
    const location = locate(timeline, timeline.totalMs + 60_000);
    expect(location.stepIndex).toBe(2);
    expect(location.stepPositionMs).toBe(6000);
  });

  it('round-trips global <-> step positions', () => {
    const global = globalPositionOf(timeline, 1, 2500);
    expect(global).toBe(12_500);
    expect(locate(timeline, global).stepIndex).toBe(1);
    expect(locate(timeline, global).stepPositionMs).toBe(2500);
  });

  it('clamps out-of-range step positions instead of producing negatives', () => {
    expect(globalPositionOf(timeline, 0, -500)).toBe(0);
    expect(globalPositionOf(timeline, 0, 99_999)).toBe(10_000);
  });

  it('handles an empty bundle without throwing', () => {
    const empty = buildCourseTimeline(null);
    expect(empty.totalMs).toBe(0);
    expect(locate(empty, 0).stepIndex).toBe(-1);
  });
});

describe('speed and formatting', () => {
  it('cycles through the five speeds', () => {
    expect(nextSpeed(0.75)).toBe(1);
    expect(nextSpeed(2)).toBe(0.75);
    expect(nextSpeed(1.1)).toBe(1);
  });

  it('formats clocks as m:ss without negative values', () => {
    expect(formatClock(0)).toBe('0:00');
    expect(formatClock(65_000)).toBe('1:05');
    expect(formatClock(-10)).toBe('0:00');
  });
});
