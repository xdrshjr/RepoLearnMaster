'use client';

import { createContext, useContext } from 'react';

import type { CourseDetail, LessonSection, PlaybackBundle } from '@/lib/api/types';
import type { CourseLayer } from '@/components/shell/top-progress';

export interface AnchorTarget {
  file: string;
  lineStart: number;
  lineEnd: number;
}

export interface CourseContextValue {
  courseId: string;
  layer: CourseLayer;
  course: CourseDetail | undefined;
  sections: LessonSection[];
  lessonKey: string | null;
  playback: PlaybackBundle | undefined;
  playbackLoading: boolean;
  /** Jump the (read-only) IDE to a source anchor; cross-layer jumps navigate. */
  openAnchor: (target: AnchorTarget) => void;
  /** Open the ask panel for a line range on the deep-dive layer. */
  askAboutRange: (target: AnchorTarget) => void;
  completedLessons: Set<string>;
}

export const CourseContext = createContext<CourseContextValue | null>(null);

export function useCourseContext(): CourseContextValue {
  const context = useContext(CourseContext);
  if (!context) {
    throw new Error('useCourseContext must be used inside <CourseShell>');
  }
  return context;
}

/** Lesson key used by a layer when the URL carries no `?lesson=`. */
export function defaultLessonForLayer(sections: LessonSection[], layer: CourseLayer): string | null {
  const index = layer === 'overview' ? 0 : layer === 'walkthrough' ? 1 : layer === 'deep-dive' ? 2 : 3;
  const byIndex = sections[index]?.lessons?.[0]?.key;
  if (byIndex) return byIndex;
  // Chapters may be merged in a degraded (template) course; fall back to any.
  return sections[0]?.lessons?.[0]?.key ?? null;
}
