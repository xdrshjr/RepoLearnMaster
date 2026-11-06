'use client';

import { Check, HelpCircle, X } from 'lucide-react';
import { useState } from 'react';

import { Badge, Card } from '@/components/ui/card';
import { Markdown } from '@/components/ui/markdown';
import { useQuizAnswer } from '@/lib/api/hooks';
import type { EvidenceView, QuizItem } from '@/lib/api/types';
import { toEvidence } from '@/lib/api/types';
import { cn } from '@/lib/utils';

/**
 * Prediction quiz — present on all three layers (spec §7.2).
 *
 * Feedback is announced immediately through `aria-live` (§7.6), and every
 * explanation carries clickable evidence so the learner can verify the answer
 * against `file:line` instead of trusting the quiz.
 */
export function PredictionQuiz({
  courseId,
  items,
  title = '预测一下再继续',
  lessonKey,
  onJumpEvidence,
}: {
  courseId: string;
  items: QuizItem[];
  title?: string;
  lessonKey?: string;
  onJumpEvidence?: (evidence: EvidenceView) => void;
}) {
  if (items.length === 0) return null;

  return (
    <Card className="space-y-3">
      <div className="flex items-center gap-1.5">
        <HelpCircle className="size-3.5 text-accent" aria-hidden />
        <h3 className="text-xs font-semibold text-text">{title}</h3>
        <span className="ml-auto text-[10px] text-text-dim">{items.length} 题</span>
      </div>
      <div className="space-y-3">
        {items.map((item) => (
          <QuizQuestion
            key={item.id}
            courseId={courseId}
            item={item}
            lessonKey={lessonKey}
            onJumpEvidence={onJumpEvidence}
          />
        ))}
      </div>
    </Card>
  );
}

function QuizQuestion({
  courseId,
  item,
  lessonKey,
  onJumpEvidence,
}: {
  courseId: string;
  item: QuizItem;
  lessonKey?: string;
  onJumpEvidence?: (evidence: EvidenceView) => void;
}) {
  const answer = useQuizAnswer(courseId);
  const [choice, setChoice] = useState<string | null>(null);
  const [result, setResult] = useState<{
    correct: boolean;
    explanation_md: string;
    evidence: EvidenceView[];
    replayed: boolean;
  } | null>(null);

  const submit = (choiceId: string) => {
    setChoice(choiceId);
    answer.mutate(
      { itemId: item.id, choiceId },
      {
        onSuccess: (data) => {
          setResult({
            correct: data.correct,
            explanation_md: data.explanation_md,
            evidence: (data.evidence ?? []).map(toEvidence).filter((value): value is EvidenceView => Boolean(value)),
            replayed: data.replayed,
          });
        },
        onError: () => {
          // A failed submit keeps the local choice so the user can retry.
          setChoice(null);
        },
      },
    );
  };

  return (
    <div className="rounded-[var(--radius-sm)] border border-border bg-surface-2/40 p-3">
      <p className="text-xs leading-[1.65] text-text">{item.stem}</p>
      <div className="mt-2 space-y-1">
        {item.choices.map((option) => {
          const active = choice === option.id;
          const isAnswer = result ? option.id === item.answer_id : false;
          return (
            <button
              key={option.id}
              type="button"
              disabled={Boolean(result)}
              onClick={() => submit(option.id)}
              aria-pressed={active}
              className={cn(
                'flex w-full items-center gap-2 rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-left text-[11px] transition-colors',
                result
                  ? isAnswer
                    ? 'border-accent/50 bg-accent-soft text-text'
                    : active
                      ? 'border-danger/40 bg-danger/10 text-text'
                      : 'border-border text-text-dim'
                  : active
                    ? 'border-accent bg-accent-soft text-text'
                    : 'border-border text-text-muted hover:border-border-strong hover:text-text',
              )}
            >
              <span className="grid size-4 shrink-0 place-items-center rounded-full border border-current text-[9px]">
                {option.id}
              </span>
              <span className="min-w-0 flex-1">{option.text}</span>
              {result && isAnswer ? <Check className="size-3 text-accent" aria-hidden /> : null}
              {result && active && !isAnswer ? <X className="size-3 text-danger" aria-hidden /> : null}
            </button>
          );
        })}
      </div>

      <div aria-live="polite" className="mt-2">
        {result ? (
          <div
            className={cn(
              'rounded-[var(--radius-sm)] border px-2.5 py-2',
              result.correct ? 'border-accent/40 bg-accent-soft' : 'border-warn/40 bg-warn/5',
            )}
          >
            <p className={cn('text-[11px] font-medium', result.correct ? 'text-accent' : 'text-warn')}>
              {result.correct ? '回答正确' : '再想想：看看下面的解释与证据'}
              {result.replayed ? <span className="ml-1 text-text-dim">（重复提交，返回首次结果）</span> : null}
            </p>
            {result.explanation_md ? (
              <Markdown compact className="mt-1.5">
                {result.explanation_md}
              </Markdown>
            ) : null}
            {result.evidence.length > 0 ? (
              <ul className="mt-2 space-y-1">
                {result.evidence.map((evidence, index) => (
                  <li key={`${evidence.file}-${evidence.line_start}-${index}`}>
                    <button
                      type="button"
                      onClick={() => onJumpEvidence?.(evidence)}
                      className="font-mono text-[10px] text-info underline decoration-dotted underline-offset-2 hover:text-accent"
                    >
                      {evidence.file}:{evidence.line_start}
                      {evidence.symbol ? ` · ${evidence.symbol}` : ''}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : answer.isPending ? (
          <p className="text-[11px] text-text-dim">正在判题…</p>
        ) : null}
      </div>

      {lessonKey ? <Badge tone="muted" className="mt-2">lesson {lessonKey}</Badge> : null}
    </div>
  );
}
