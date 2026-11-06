'use client';

/**
 * Playback store — spec §7.5.
 *
 * The player state deliberately does NOT live in the TanStack Query cache:
 * position updates arrive ~10×/second and would thrash the cache. This store is
 * the single source of truth for the transport bar, subtitle view, code
 * highlight and board actions (§7.3 rule 1).
 */

import { create } from 'zustand';

import type { PlaybackBundle } from '@/lib/api/types';
import {
  buildCourseTimeline,
  clamp,
  findStepIndex,
  globalPositionOf,
  locate,

  type CourseTimeline,
  type PlaybackSpeed,
} from '@/lib/player/timeline';

export type PlayerStatus = 'idle' | 'loading' | 'ready' | 'playing' | 'paused' | 'ended' | 'seeking';

export interface PlayerStore {
  courseId: string | null;
  lessonKey: string | null;
  bundle: PlaybackBundle | null;
  timeline: CourseTimeline;
  status: PlayerStatus;
  stepIndex: number;
  /** Position inside the current step, in ms. */
  positionMs: number;
  speed: PlaybackSpeed;
  captionsOn: boolean;
  shortcutsOpen: boolean;
  /** True when any step relies on estimated timing / teaching simulation. */
  simulationOnly: boolean;

  loadBundle: (bundle: PlaybackBundle, options?: { autoplay?: boolean }) => void;
  setStatus: (status: PlayerStatus) => void;
  setPosition: (positionMs: number) => void;
  setStep: (stepIndex: number, positionMs?: number) => void;
  play: () => void;
  pause: () => void;
  togglePlay: () => void;
  nextStep: () => void;
  prevStep: () => void;
  seekStep: (positionMs: number) => void;
  seekGlobal: (globalMs: number) => void;
  nudge: (deltaMs: number) => void;
  setSpeed: (speed: PlaybackSpeed) => void;
  toggleCaptions: () => void;
  toggleShortcuts: (open?: boolean) => void;
  reset: () => void;
}

const initial = {
  courseId: null as string | null,
  lessonKey: null as string | null,
  bundle: null as PlaybackBundle | null,
  timeline: { steps: [], offsets: [], totalMs: 0 } as CourseTimeline,
  status: 'idle' as PlayerStatus,
  stepIndex: 0,
  positionMs: 0,
  speed: 1 as PlaybackSpeed,
  captionsOn: true,
  shortcutsOpen: false,
  simulationOnly: false,
};

export const usePlayerStore = create<PlayerStore>((set, get) => ({
  ...initial,

  loadBundle: (bundle, options) => {
    if (bundle.steps.length === 0) {
      set({ ...initial, courseId: bundle.course_id, lessonKey: bundle.lesson.key, status: 'ready' });
      return;
    }
    const timeline = buildCourseTimeline(bundle);
    const simulationOnly = timeline.steps.some(
      (step) => step.timingSource === 'estimated' || step.audioUrl === null,
    );
    set({
      courseId: bundle.course_id,
      lessonKey: bundle.lesson.key,
      bundle,
      timeline,
      status: options?.autoplay ? 'playing' : 'ready',
      stepIndex: 0,
      positionMs: 0,
      simulationOnly,
    });
  },

  setStatus: (status) => set({ status }),

  setPosition: (positionMs) => {
    const { timeline, stepIndex } = get();
    const step = timeline.steps[stepIndex];
    if (!step) {
      set({ positionMs: 0, status: 'ended' });
      return;
    }
    const bounded = clamp(positionMs, 0, step.durationMs);
    const atEnd = globalPositionOf(timeline, stepIndex, bounded) >= timeline.totalMs - 1;
    set({ positionMs: bounded, status: atEnd ? 'ended' : get().status === 'seeking' ? 'playing' : get().status });
  },

  setStep: (stepIndex, positionMs = 0) => {
    const { timeline } = get();
    if (timeline.steps.length === 0) return;
    const boundedIndex = clamp(Math.round(stepIndex), 0, timeline.steps.length - 1);
    const step = timeline.steps[boundedIndex]!;
    set({ stepIndex: boundedIndex, positionMs: clamp(positionMs, 0, step.durationMs) });
  },

  play: () => {
    const { timeline, stepIndex, positionMs, status } = get();
    if (timeline.steps.length === 0) return;
    const step = timeline.steps[stepIndex];
    if (!step) return;
    if (status === 'ended' || positionMs >= step.durationMs - 1) {
      // Restart the lesson from the beginning when the user hits play at the end.
      const isLastStep = stepIndex === timeline.steps.length - 1;
      if (status === 'ended' || isLastStep) {
        set({ stepIndex: 0, positionMs: 0, status: 'playing' });
        return;
      }
    }
    set({ status: 'playing' });
  },

  pause: () => set({ status: get().status === 'ended' ? 'ended' : 'paused' }),

  togglePlay: () => {
    const status = get().status;
    if (status === 'playing') get().pause();
    else get().play();
  },

  nextStep: () => {
    const { stepIndex, timeline } = get();
    if (timeline.steps.length === 0) return;
    if (stepIndex >= timeline.steps.length - 1) {
      const last = timeline.steps[timeline.steps.length - 1]!;
      set({ positionMs: last.durationMs, status: 'ended' });
      return;
    }
    set({ stepIndex: stepIndex + 1, positionMs: 0 });
  },

  prevStep: () => {
    const { stepIndex } = get();
    set({ stepIndex: Math.max(0, stepIndex - 1), positionMs: 0 });
  },

  seekStep: (positionMs) => {
    const { timeline, stepIndex } = get();
    const step = timeline.steps[stepIndex];
    if (!step) return;
    set({ positionMs: clamp(positionMs, 0, step.durationMs) });
  },

  seekGlobal: (globalMs) => {
    const { timeline } = get();
    if (timeline.steps.length === 0) return;
    const bounded = clamp(globalMs, 0, timeline.totalMs);
    const stepIndex = findStepIndex(timeline, bounded);
    const offset = timeline.offsets[stepIndex] ?? 0;
    const step = timeline.steps[stepIndex]!;
    set({ stepIndex, positionMs: clamp(bounded - offset, 0, step.durationMs) });
  },

  nudge: (deltaMs) => {
    const { timeline, stepIndex, positionMs } = get();
    const step = timeline.steps[stepIndex];
    if (!step) return;
    const target = positionMs + deltaMs;
    if (target > step.durationMs && stepIndex < timeline.steps.length - 1) {
      const overflow = target - step.durationMs;
      const next = timeline.steps[stepIndex + 1]!;
      set({ stepIndex: stepIndex + 1, positionMs: clamp(overflow, 0, next.durationMs) });
      return;
    }
    set({ positionMs: clamp(target, 0, step.durationMs) });
  },

  setSpeed: (speed) => set({ speed }),
  toggleCaptions: () => set({ captionsOn: !get().captionsOn }),
  toggleShortcuts: (open) => set({ shortcutsOpen: open ?? !get().shortcutsOpen }),

  reset: () => set({ ...initial }),
}));

/** Current step duration (0 when nothing is loaded). */
export function currentStepDuration(state: PlayerStore): number {
  return state.timeline.steps[state.stepIndex]?.durationMs ?? 0;
}

/** Derived view of "what is true at the current time" (segments/board/focus). */
export function currentLocation(state: PlayerStore) {
  const globalMs = globalPositionOf(state.timeline, state.stepIndex, state.positionMs);
  return locate(state.timeline, globalMs);
}
