'use client';

import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { Waypoints } from 'lucide-react';

import { Badge, Card, EmptyState } from '@/components/ui/card';
import { CodePane } from '@/components/ide/code-pane';
import { CallChainSheet } from '@/components/learning/call-chain-sheet';
import { SimulationBanner } from '@/components/learning/certainty-badge';
import { PredictionQuiz } from '@/components/learning/prediction-quiz';
import { TraceStepDetail, TraceStrip } from '@/components/learning/trace-strip';
import { useCourseContext } from '@/components/shell/course-context';
import { evidenceToAnchor, evidenceViews, useLayerData, useSyncFocus } from '@/components/learning/use-layer-data';
import { useIdeStore } from '@/stores/ide';
import { usePlayerStore } from '@/stores/player';

/**
 * P04 全局走读 — spec §7.2 第二层.
 *
 * TraceStrip + variable panel with sample-value markers + certainty badges and a
 * permanent teaching-simulation banner; “查看调用链” opens the CallChainSheet.
 */
export default function WalkthroughPage() {
  const router = useRouter();
  const { courseId, playback, lessonKey, openAnchor } = useCourseContext();
  const { step, codeNotes, quiz } = useLayerData();
  const stepIndex = usePlayerStore((state) => state.stepIndex);
  const timeline = usePlayerStore((state) => state.timeline);
  const seekGlobal = usePlayerStore((state) => state.seekGlobal);
  const focus = useIdeStore((state) => state.focus);
  const [callChainOpen, setCallChainOpen] = useState(false);
  const [manualTraceIndex, setManualTraceIndex] = useState<number | null>(null);

  useSyncFocus();

  const traceSteps = playback?.trace?.steps ?? [];
  // The trace step tracks the narration step until the learner clicks a card.
  const derivedIndex = Math.min(Math.max(0, traceSteps.length - 1), Math.max(0, stepIndex));
  const traceIndex = manualTraceIndex ?? derivedIndex;
  const activeTrace = traceSteps[traceIndex] ?? null;
  const evidence = evidenceViews(activeTrace);

  if (!playback) {
    return (
      <div className="p-4">
        <EmptyState title="第二层还没准备好" description="走读脚本正在生成；已发布的课时可从左侧大纲切换。" />
      </div>
    );
  }

  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Waypoints className="size-4 text-accent" aria-hidden />
        <h2 className="text-xs font-semibold text-text">第二层 · 全局走读</h2>
        <Badge tone="muted">{playback.lesson.title}</Badge>
        <Badge tone="info">步骤 {stepIndex + 1}/{timeline.steps.length || 1}</Badge>
      </div>

      <SimulationBanner
        note={
          playback.trace?.certainty_summary
            ? `确定性统计：${Object.entries(playback.trace.certainty_summary)
                .map(([key, value]) => `${key}=${String(value)}`)
                .join(' · ')}`
            : undefined
        }
      />

      <TraceStrip
        steps={traceSteps}
        currentIndex={traceIndex}
        onSelect={(index) => {
          setManualTraceIndex(index);
          const matchingStep = timeline.steps.findIndex(
            (item) => item.title === traceSteps[index]?.title,
          );
          if (matchingStep >= 0) seekGlobal(timeline.offsets[matchingStep] ?? 0);
        }}
        onOpenCallChain={() => setCallChainOpen(true)}
      />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <div className="space-y-3">
          {activeTrace ? (
            <TraceStepDetail step={activeTrace} onJump={(item) => openAnchor(evidenceToAnchor(item))} />
          ) : (
            <Card className="text-[11px] text-text-dim">
              本节没有调用链数据。可以继续听讲解，或在右侧读代码。
            </Card>
          )}

          <Card className="space-y-2">
            <h3 className="text-xs font-semibold text-text">当前讲解</h3>
            <ul className="space-y-1.5">
              {(step?.segments ?? []).slice(0, 6).map((segment) => (
                <li key={segment.id} className="flex gap-2 text-[11px] leading-[1.65]">
                  <span className="shrink-0 font-mono text-[10px] text-text-dim">
                    {(segment.startMs / 1000).toFixed(1)}s
                  </span>
                  <span className="min-w-0 flex-1 text-text-muted">{segment.text}</span>
                  {segment.focus ? (
                    <button
                      type="button"
                      onClick={() =>
                        openAnchor({
                          file: segment.focus!.file,
                          lineStart: segment.focus!.line_start,
                          lineEnd: segment.focus!.line_end,
                        })
                      }
                      className="shrink-0 font-mono text-[10px] text-info underline decoration-dotted underline-offset-2"
                    >
                      L{segment.focus.line_start}
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <CodePane
          courseId={courseId}
          files={playback.files}
          codeNotes={codeNotes}
          evidence={evidence}
          onAsk={(next) =>
            router.push(
              `/course/${encodeURIComponent(courseId)}/deep-dive?file=${encodeURIComponent(
                focus?.file ?? playback.files[0]?.path ?? '',
              )}&line=${next.lineStart}&ask=1`,
            )
          }
          className="min-h-[420px] lg:min-h-[600px]"
        />
      </div>

      <PredictionQuiz
        courseId={courseId}
        items={quiz.slice(0, 2)}
        lessonKey={lessonKey ?? undefined}
        title="走读中检查：下一步会发生什么？"
        onJumpEvidence={(item) => openAnchor(evidenceToAnchor(item))}
      />

      <CallChainSheet
        open={callChainOpen}
        onClose={() => setCallChainOpen(false)}
        steps={traceSteps}
        onJump={(item) => openAnchor(evidenceToAnchor(item))}
      />
    </div>
  );
}
