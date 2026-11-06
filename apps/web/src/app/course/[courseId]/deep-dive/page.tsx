'use client';

import { useSearchParams } from 'next/navigation';
import { Braces, FileCode2, MessageSquarePlus, Terminal, Waypoints } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { Badge, Card, EmptyState } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Tabs } from '@/components/ui/overlay';
import { CodePane } from '@/components/ide/code-pane';
import { CallChainSheet } from '@/components/learning/call-chain-sheet';
import { SimulationBanner } from '@/components/learning/certainty-badge';
import { InlineAsk } from '@/components/learning/inline-ask';
import { PredictionQuiz } from '@/components/learning/prediction-quiz';
import { CertaintyBadge } from '@/components/learning/certainty-badge';
import { useCourseContext } from '@/components/shell/course-context';
import { evidenceToAnchor, evidenceViews, useLayerData, useSyncFocus } from '@/components/learning/use-layer-data';
import type { AskActionId } from '@/lib/ide/decorations';
import { useIdeStore } from '@/stores/ide';
import { usePlayerStore } from '@/stores/player';
import { cn } from '@/lib/utils';

type PanelTab = 'execution' | 'variables';

/**
 * P05 深入源码 — spec §7.2 第三层 / 行内提问.
 *
 * Monaco main pane with decorations, execution/variable panel, and the streaming
 * inline-question panel that is opened either from the selection toolbar or from
 * Momo's “选中代码问 Momo”.
 */
export default function DeepDivePage() {
  const searchParams = useSearchParams();
  const { courseId, playback, lessonKey, openAnchor } = useCourseContext();
  const { step, codeNotes, quiz } = useLayerData();
  const stepIndex = usePlayerStore((state) => state.stepIndex);
  const timeline = usePlayerStore((state) => state.timeline);
  const seekGlobal = usePlayerStore((state) => state.seekGlobal);
  const selection = useIdeStore((state) => state.selection);
  const askOpen = useIdeStore((state) => state.askOpen);
  const setAskOpen = useIdeStore((state) => state.setAskOpen);
  const files = useIdeStore((state) => state.files);
  const openFile = useIdeStore((state) => state.openFile);
  const activeFile = useIdeStore((state) => state.activeFile);
  const setSelection = useIdeStore((state) => state.setSelection);

  const [tab, setTab] = useState<PanelTab>('execution');
  const [callChainOpen, setCallChainOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<AskActionId | null>(null);

  useSyncFocus();

  const traceSteps = playback?.trace?.steps ?? [];
  const traceStep = traceSteps[Math.min(stepIndex, Math.max(0, traceSteps.length - 1))] ?? null;
  const evidence = evidenceViews(traceStep);
  const paneFiles = files.length > 0 ? files : (playback?.files ?? []);

  // `?ask=1` (arriving from Momo / another layer) opens the ask panel directly.
  useEffect(() => {
    if (searchParams.get('ask') !== '1') return;
    setAskOpen(true);
  }, [searchParams, setAskOpen]);

  const askSelection = useMemo(() => {
    if (selection) return selection;
    const file = activeFile ?? paneFiles[0]?.path;
    if (!file) return null;
    return { file, lineStart: 1, lineEnd: 1, text: '' };
  }, [selection, activeFile, paneFiles]);

  if (!playback) {
    return (
      <div className="p-4">
        <EmptyState title="第三层还没准备好" description="深入源码的课时正在生成。可以先回到前两层。" />
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <FileCode2 className="size-4 text-accent" aria-hidden />
        <h2 className="text-xs font-semibold text-text">第三层 · 深入源码</h2>
        <Badge tone="muted">{playback.lesson.title}</Badge>
        <span className="ml-auto flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setCallChainOpen(true)}
            icon={<Waypoints className="size-3" aria-hidden />}
          >
            调用链
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setPendingAction('explain');
              setAskOpen(true);
            }}
            icon={<MessageSquarePlus className="size-3" aria-hidden />}
          >
            选中代码问 Momo
          </Button>
        </span>
      </div>

      <SimulationBanner note="带波浪下划线的行是 trace 证据；左侧绿色条是当前讲解焦点。" />

      {/* File tabs: opening a file must never unmount the player (it lives in the shell). */}
      <div className="flex items-center gap-1 overflow-x-auto rl-scroll-thin" role="tablist" aria-label="打开的文件">
        {paneFiles.slice(0, 8).map((file) => {
          const active = file.path === activeFile;
          const name = file.path.split('/').pop() ?? file.path;
          return (
            <button
              key={file.path}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => openFile(file.path)}
              title={file.path}
              className={cn(
                'flex shrink-0 items-center gap-1 rounded-t-[var(--radius-sm)] border border-b-0 px-2 py-1 font-mono text-[10px] transition-colors',
                active
                  ? 'border-border bg-code-bg text-text'
                  : 'border-transparent text-text-dim hover:text-text',
              )}
            >
              {name}
              <span className="text-text-dim">{file.lang}</span>
            </button>
          );
        })}
      </div>

      <div className="grid min-h-0 flex-1 gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]">
        <CodePane
          courseId={courseId}
          files={paneFiles}
          codeNotes={codeNotes}
          evidence={evidence}
          onAsk={(next) => {
            setSelection({ file: activeFile ?? paneFiles[0]?.path ?? '', ...next });
            setAskOpen(true);
          }}
          className="min-h-[480px] xl:min-h-[620px]"
        />

        <div className="space-y-3">
          <Card className="space-y-2 p-0">
            <Tabs
              tabs={[
                { value: 'execution', label: '执行模拟', badge: traceSteps.length || undefined },
                { value: 'variables', label: '变量状态', badge: traceStep?.variables.length || undefined },
              ]}
              value={tab}
              onChange={setTab}
              ariaLabel="执行面板"
              className="px-2 pt-1"
            />
            <div className="max-h-[260px] overflow-y-auto px-3 pb-3 rl-scroll-thin">
              {tab === 'execution' ? (
                traceSteps.length === 0 ? (
                  <p className="text-[11px] text-text-dim">本节没有执行模拟数据。</p>
                ) : (
                  <ol className="space-y-1.5">
                    {traceSteps.map((item, index) => (
                      <li key={`${item.index}-${item.title}`}>
                        <button
                          type="button"
                          onClick={() => {
                            const matching = timeline.steps.findIndex((s) => s.title === item.title);
                            if (matching >= 0) seekGlobal(timeline.offsets[matching] ?? 0);
                          }}
                          className={cn(
                            'flex w-full items-center gap-1.5 rounded-[var(--radius-sm)] px-1.5 py-1 text-left text-[11px]',
                            index === stepIndex ? 'bg-accent-soft text-accent' : 'text-text-muted hover:bg-surface-2',
                          )}
                        >
                          <span className="grid size-4 shrink-0 place-items-center rounded-full border border-current text-[9px]">
                            {index + 1}
                          </span>
                          <span className="min-w-0 flex-1 truncate">{item.title}</span>
                          <CertaintyBadge certainty={item.certainty} />
                        </button>
                      </li>
                    ))}
                  </ol>
                )
              ) : (
                <div className="space-y-1.5">
                  {(traceStep?.variables ?? []).length === 0 ? (
                    <p className="text-[11px] text-text-dim">当前步骤没有可见变量。</p>
                  ) : (
                    (traceStep?.variables ?? []).map((variable, index) => (
                      <div key={index} className="rounded-[var(--radius-sm)] border border-border bg-code-bg px-2 py-1">
                        <div className="flex items-baseline gap-2">
                          <span className="font-mono text-[10px] text-accent">{String(variable.name ?? '')}</span>
                          <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-text">
                            {String(variable.value ?? '')}
                          </span>
                        </div>
                        {typeof variable.note === 'string' ? (
                          <p className="mt-0.5 text-[10px] text-warn">{variable.note}</p>
                        ) : null}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </Card>

          {codeNotes.filter((note) => note.file === activeFile).length > 0 ? (
            <Card className="space-y-1.5">
              <h3 className="flex items-center gap-1.5 text-xs font-semibold text-text">
                <Braces className="size-3.5 text-accent" aria-hidden />
                本文件代码注释
              </h3>
              <ul className="max-h-40 space-y-1 overflow-y-auto rl-scroll-thin">
                {codeNotes
                  .filter((note) => note.file === activeFile)
                  .map((note) => (
                    <li key={`${note.line}-${note.text}`}>
                      <button
                        type="button"
                        onClick={() =>
                          openAnchor({ file: note.file, lineStart: note.line, lineEnd: note.line })
                        }
                        className="flex w-full gap-2 rounded-[var(--radius-sm)] px-1.5 py-1 text-left hover:bg-surface-2"
                      >
                        <span className="shrink-0 font-mono text-[10px] text-accent">L{note.line}</span>
                        <span className="min-w-0 flex-1 text-[11px] leading-[1.55] text-text-muted">
                          {note.text}
                        </span>
                      </button>
                    </li>
                  ))}
              </ul>
            </Card>
          ) : null}

          {askOpen && askSelection ? (
            <InlineAsk
              courseId={courseId}
              selection={askSelection}
              layer="deep_dive"
              lessonKey={lessonKey}
              initialAction={pendingAction}
              onJumpEvidence={(item) => openAnchor(evidenceToAnchor(item))}
              onClose={() => {
                setAskOpen(false);
                setPendingAction(null);
              }}
            />
          ) : (
            <Card className="space-y-1.5">
              <h3 className="flex items-center gap-1.5 text-xs font-semibold text-text">
                <Terminal className="size-3.5 text-accent" aria-hidden />
                怎么提问
              </h3>
              <p className="text-[11px] leading-[1.65] text-text-muted">
                在左侧代码里选中任意几行 → 出现浮动工具条（解释这行 / 为什么这样实现 / 有什么替代方案）→
                答案会带证据列表，点一下跳回 file:line。
              </p>
            </Card>
          )}
        </div>
      </div>

      <PredictionQuiz
        courseId={courseId}
        items={quiz.slice(0, 2)}
        lessonKey={lessonKey ?? undefined}
        title="源码细节检查"
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
