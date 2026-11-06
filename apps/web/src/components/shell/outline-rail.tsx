'use client';

import Link from 'next/link';
import { Check, Circle, Clock, Target } from 'lucide-react';

import { Badge } from '@/components/ui/card';
import type { LessonSection } from '@/lib/api/types';
import type { CourseLayer } from '@/components/shell/top-progress';
import { cn } from '@/lib/utils';

/**
 * Outline rail — 4 chapters, sub-lessons, learning goals and check states
 * (spec §7.2). On narrow screens the shell turns this into a drawer.
 */
export function OutlineRail({
  courseId,
  sections,
  layer,
  lessonKey,
  completedLessons,
  onSelect,
}: {
  courseId: string;
  sections: LessonSection[];
  layer: CourseLayer;
  lessonKey: string | null;
  completedLessons: Set<string>;
  onSelect: (key: string) => void;
}) {
  if (sections.length === 0) {
    return (
      <div className="p-3 text-[11px] text-text-dim">
        大纲还没生成。等“宏观架构”这一段点亮后会出现 4 章结构。
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 className="text-[11px] font-semibold text-text">课程大纲</h2>
        <span className="text-[10px] text-text-dim">
          {completedLessons.size}/{sections.reduce((sum, section) => sum + section.lessons.length, 0)}
        </span>
      </div>
      <ol className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2 rl-scroll-thin">
        {sections.map((section, sectionIndex) => {
          const lessons = section.lessons ?? [];
          return (
            <li key={section.key}>
              <div className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="grid size-4 shrink-0 place-items-center rounded-full bg-surface-2 text-[9px] text-text-muted"
                >
                  {sectionIndex + 1}
                </span>
                <h3 className="min-w-0 flex-1 truncate text-[11px] font-medium text-text">{section.title}</h3>
                <span className="inline-flex shrink-0 items-center gap-0.5 text-[10px] text-text-dim">
                  <Clock className="size-2.5" aria-hidden />
                  {section.minutes}
                </span>
              </div>

              <ul className="mt-1 space-y-0.5 border-l border-border pl-2">
                {lessons.map((lesson) => {
                  const active = lesson.key === lessonKey;
                  const done = completedLessons.has(lesson.key);
                  const goal =
                    typeof lesson.goal === 'string' && lesson.goal
                      ? lesson.goal
                      : typeof lesson.title === 'string'
                        ? lesson.title
                        : lesson.key;
                  return (
                    <li key={lesson.key}>
                      <Link
                        href={`/course/${encodeURIComponent(courseId)}/${layer}?lesson=${encodeURIComponent(lesson.key)}`}
                        onClick={() => onSelect(lesson.key)}
                        aria-current={active ? 'true' : undefined}
                        className={cn(
                          'flex items-start gap-1.5 rounded-[var(--radius-sm)] px-1.5 py-1 transition-colors',
                          active ? 'bg-accent-soft text-accent' : 'text-text-muted hover:bg-surface-2 hover:text-text',
                        )}
                      >
                        {done ? (
                          <Check className="mt-0.5 size-3 shrink-0 text-accent" aria-hidden />
                        ) : (
                          <Circle className="mt-0.5 size-2.5 shrink-0 opacity-50" aria-hidden />
                        )}
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[11px]">{lesson.title || lesson.key}</span>
                          <span className="mt-0.5 flex items-center gap-1 text-[10px] text-text-dim">
                            <Target className="size-2.5 shrink-0" aria-hidden />
                            <span className="truncate">{goal}</span>
                          </span>
                        </span>
                        {typeof lesson.minutes === 'number' && lesson.minutes > 0 ? (
                          <span className="shrink-0 text-[9px] text-text-dim">{lesson.minutes}′</span>
                        ) : null}
                      </Link>
                    </li>
                  );
                })}
                {lessons.length === 0 ? (
                  <li className="px-1.5 py-1 text-[10px] text-text-dim">本章还没有课时</li>
                ) : null}
              </ul>
            </li>
          );
        })}
      </ol>
      <div className="border-t border-border px-3 py-2">
        <Badge tone="muted">学习目标随播放自动勾选</Badge>
      </div>
    </div>
  );
}
