'use client';

import { useRouter } from 'next/navigation';
import { Boxes, Check, Target } from 'lucide-react';
import { useMemo } from 'react';

import { Badge, Card, CardHeader, EmptyState } from '@/components/ui/card';
import { ArchitectureCanvas, ConceptCard, type AnchorJump } from '@/components/learning/architecture-canvas';
import { CodePane } from '@/components/ide/code-pane';
import { PredictionQuiz } from '@/components/learning/prediction-quiz';
import { useCourseContext } from '@/components/shell/course-context';
import { evidenceViews, useLayerData, useSyncFocus } from '@/components/learning/use-layer-data';
import { useIdeStore } from '@/stores/ide';
import { usePlayerStore } from '@/stores/player';

/**
 * P03 宏观架构 — spec §7.2 第一层.
 *
 * Architecture canvas + concept cards + entry code pane + prediction quiz.
 * Clicking a node jumps the code pane to its anchor line (local, no navigation).
 */
export default function OverviewPage() {
  const router = useRouter();
  const { courseId, course, playback, lessonKey, sections, openAnchor } = useCourseContext();
  const { step, codeNotes, quiz, segment } = useLayerData();
  const stepIndex = usePlayerStore((state) => state.stepIndex);
  const focus = useIdeStore((state) => state.focus);
  const seekGlobal = usePlayerStore((state) => state.seekGlobal);
  const timeline = usePlayerStore((state) => state.timeline);

  useSyncFocus();

  const traceSteps = playback?.trace?.steps ?? [];
  const evidence = useMemo(
    () => evidenceViews(traceSteps[Math.min(stepIndex, Math.max(0, traceSteps.length - 1))] ?? null),
    [traceSteps, stepIndex],
  );

  const concepts = useMemo(() => {
    const fromTrace = traceSteps.slice(0, 3).map((item) => ({
      title: item.title,
      body: item.note || '这一步是整体流程的一环，展开全局走读可以看到完整调用链。',
      evidence: evidenceViews(item).slice(0, 2).map((value) => ({
        file: value.file,
        line_start: value.line_start,
        line_end: value.line_end,
        symbol: value.symbol,
      })),
    }));
    if (fromTrace.length > 0) return fromTrace;
    return (playback?.trace?.steps ?? []).map((item) => ({ title: item.title, body: item.note ?? '', evidence: [] }));
  }, [traceSteps, playback]);

  const lessonGoal = useMemo(() => {
    const lessons = sections.flatMap((section) => section.lessons);
    const current = lessons.find((lesson) => lesson.key === lessonKey);
    const goal = current && typeof current.goal === 'string' ? current.goal : null;
    return goal ?? course?.subtitle ?? '看懂这个仓库的整体形状：它由哪些模块组成、请求从哪里进、在哪里出。';
  }, [sections, lessonKey, course?.subtitle]);

  const handleJump = (target: AnchorJump) => {
    openAnchor({
      file: target.file,
      lineStart: target.lineStart,
      lineEnd: target.lineEnd,
    });
    const matching = timeline.steps.findIndex((item) =>
      item.segments.some((seg) => seg.focus?.file === target.file && seg.focus.line_start === target.lineStart),
    );
    if (matching >= 0) {
      seekGlobal(timeline.offsets[matching] ?? 0);
    }
  };

  if (!playback) {
    return (
      <div className="p-4">
        <EmptyState
          title="第一层还没准备好"
          description="课程的宏观架构层正在生成。已发布的课时可以先从大纲里切换。"
        />
      </div>
    );
  }

  return (
    <div className="space-y-3 p-3">
      <Card className="flex flex-wrap items-center gap-2 py-2.5">
        <Boxes className="size-4 text-accent" aria-hidden />
        <h2 className="text-xs font-semibold text-text">第一层 · 宏观架构</h2>
        <Badge tone="muted">{playback.lesson.title}</Badge>
        {segment?.focus ? (
          <span className="ml-auto font-mono text-[10px] text-text-dim">
            {segment.focus.file}:{segment.focus.line_start}
          </span>
        ) : null}
      </Card>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          <Card className="space-y-1.5">
            <CardHeader title="本节学习目标" subtitle={lessonGoal} />
            <ul className="space-y-1">
              {traceSteps.slice(0, 4).map((traceStep, index) => {
                const done = index <= stepIndex;
                return (
                  <li key={`${traceStep.index}-${traceStep.title}`} className="flex items-start gap-1.5 text-[11px]">
                    <span
                      aria-hidden
                      className={`mt-0.5 grid size-3.5 shrink-0 place-items-center rounded-full border ${
                        done ? 'border-accent bg-accent text-[#06110c]' : 'border-border text-transparent'
                      }`}
                    >
                      <Check className="size-2.5" />
                    </span>
                    <span className={done ? 'text-text' : 'text-text-muted'}>{traceStep.title}</span>
                  </li>
                );
              })}
              {traceSteps.length === 0 ? (
                <li className="flex items-center gap-1.5 text-[11px] text-text-dim">
                  <Target className="size-3" aria-hidden />
                  播放讲解会逐步点亮目标
                </li>
              ) : null}
            </ul>
          </Card>

          <ArchitectureCanvas board={step?.board ?? playback.steps[0]?.board ?? null} onJump={handleJump} />

          <div className="grid gap-2 sm:grid-cols-2">
            {concepts.slice(0, 2).map((concept) => (
              <ConceptCard key={concept.title} concept={concept} onJump={handleJump} />
            ))}
          </div>
        </div>

        <CodePane
          courseId={courseId}
          files={playback.files}
          codeNotes={codeNotes}
          evidence={evidence}
          onAsk={(next) => {
            // Overview is a reading layer: questions are answered on the
            // deep-dive layer, where the full IDE and evidence panel live.
            router.push(
              `/course/${encodeURIComponent(courseId)}/deep-dive?file=${encodeURIComponent(
                focus?.file ?? playback.files[0]?.path ?? '',
              )}&line=${next.lineStart}&ask=1`,
            );
          }}
          className="min-h-[420px] lg:min-h-[560px]"
        />
      </div>

      <PredictionQuiz
        courseId={courseId}
        items={quiz.slice(0, 2)}
        lessonKey={lessonKey ?? undefined}
        title="先预测：这门课的入口在哪里？"
        onJumpEvidence={(item) =>
          openAnchor({ file: item.file, lineStart: item.line_start, lineEnd: item.line_end })
        }
      />
    </div>
  );
}
