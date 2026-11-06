'use client';

import { BookOpen, Check, CircleCheckBig, Download, ListChecks, Sparkles, Trophy } from 'lucide-react';
import { useState } from 'react';

import { Badge, Card, CardHeader, EmptyState, ProgressBar } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Markdown } from '@/components/ui/markdown';
import type { RecapResponse } from '@/lib/api/types';
import { readString } from '@/lib/api/types';
import { formatDateTime } from '@/lib/format';

export function CompletionCard({
  title,
  repoFullName,
  percent,
  completed,
  minutes,
  quizStats,
  finishedAt,
}: {
  title: string;
  repoFullName: string;
  percent: number;
  completed: boolean;
  minutes: number;
  quizStats: Record<string, unknown>;
  finishedAt?: string | null;
}) {
  const correct = Number(quizStats.correct ?? quizStats.correct_count ?? 0);
  const total = Number(quizStats.total ?? quizStats.total_count ?? 0);
  return (
    <Card className="relative overflow-hidden">
      <div aria-hidden className="absolute inset-x-0 top-0 h-20 bg-gradient-to-br from-accent/25 to-transparent" />
      <div className="relative space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="flex items-center gap-1.5 text-[11px] text-accent">
              <Trophy className="size-3.5" aria-hidden />
              {completed ? '已完成' : '进行中'}
            </p>
            <h2 className="mt-1 text-lg font-semibold text-text">{title}</h2>
            <p className="text-[11px] text-text-dim">{repoFullName}</p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-semibold text-accent">{Math.round(percent)}%</p>
            <p className="text-[10px] text-text-dim">课程进度</p>
          </div>
        </div>

        <ProgressBar value={percent} label="整体完成度" />

        <dl className="grid grid-cols-3 gap-2 text-center">
          <div className="rounded-[var(--radius-sm)] border border-border px-2 py-1.5">
            <dt className="text-[10px] text-text-dim">答题</dt>
            <dd className="text-xs text-text">
              {total > 0 ? `${correct}/${total}` : '—'}
            </dd>
          </div>
          <div className="rounded-[var(--radius-sm)] border border-border px-2 py-1.5">
            <dt className="text-[10px] text-text-dim">预计时长</dt>
            <dd className="text-xs text-text">{minutes} 分钟</dd>
          </div>
          <div className="rounded-[var(--radius-sm)] border border-border px-2 py-1.5">
            <dt className="text-[10px] text-text-dim">完课时间</dt>
            <dd className="truncate text-xs text-text">{finishedAt ? formatDateTime(finishedAt) : '—'}</dd>
          </div>
        </dl>
      </div>
    </Card>
  );
}

export function KnowledgeReview({ points }: { points: Array<Record<string, unknown>> }) {
  const [checked, setChecked] = useState<Set<number>>(new Set());

  if (points.length === 0) {
    return (
      <Card>
        <CardHeader title="知识点复盘" />
        <p className="text-[11px] text-text-dim">本次没有单独记录知识点，可以直接看下面的问答明细。</p>
      </Card>
    );
  }

  return (
    <Card className="space-y-2">
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <ListChecks className="size-3.5 text-accent" aria-hidden />
            知识点复盘
          </span>
        }
        subtitle={`${checked.size}/${points.length} 已确认掌握`}
      />
      <ul className="space-y-1">
        {points.map((point, index) => {
          const text =
            readString(point, 'text') ||
            readString(point, 'title') ||
            readString(point, 'point') ||
            JSON.stringify(point).slice(0, 120);
          const detail = readString(point, 'detail') || readString(point, 'body');
          const isChecked = checked.has(index);
          return (
            <li key={index}>
              <label className="flex cursor-pointer items-start gap-2 rounded-[var(--radius-sm)] px-1.5 py-1 hover:bg-surface-2">
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => {
                    setChecked((current) => {
                      const next = new Set(current);
                      if (next.has(index)) next.delete(index);
                      else next.add(index);
                      return next;
                    });
                  }}
                  className="mt-0.5 size-3.5 accent-[var(--accent)]"
                />
                <span className="min-w-0">
                  <span className={`block text-[11px] ${isChecked ? 'text-text' : 'text-text-muted'}`}>{text}</span>
                  {detail ? <span className="mt-0.5 block text-[10px] text-text-dim">{detail}</span> : null}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export function QuizReview({ stats }: { stats: Record<string, unknown> }) {
  const items = Array.isArray(stats.items) ? (stats.items as Array<Record<string, unknown>>) : [];
  const correct = Number(stats.correct ?? stats.correct_count ?? 0);
  const total = Number(stats.total ?? stats.total_count ?? 0);

  return (
    <Card className="space-y-2">
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <CircleCheckBig className="size-3.5 text-accent" aria-hidden />
            答题复盘
          </span>
        }
        action={
          total > 0 ? (
            <Badge tone={correct === total ? 'accent' : 'warn'}>
              {correct}/{total} 正确
            </Badge>
          ) : null
        }
        subtitle="重复提交只会记一次，这里显示的是每个题目的最终结果。"
      />
      {items.length === 0 ? (
        <p className="text-[11px] text-text-dim">
          {total > 0 ? `共 ${total} 题，答对 ${correct} 题。` : '本次没有答题记录。'}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item, index) => {
            const ok = item.correct === true;
            return (
              <li key={index} className="rounded-[var(--radius-sm)] border border-border px-2 py-1.5">
                <p className="flex items-start gap-1.5 text-[11px]">
                  <span className={ok ? 'text-accent' : 'text-danger'}>{ok ? '✓' : '✗'}</span>
                  <span className="min-w-0 flex-1 text-text-muted">
                    {readString(item, 'stem') || readString(item, 'question') || `第 ${index + 1} 题`}
                  </span>
                </p>
                {readString(item, 'explanation_md') ? (
                  <Markdown compact className="mt-1 pl-5">
                    {readString(item, 'explanation_md')}
                  </Markdown>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

export function NextSteps({
  steps,
  pitfalls,
  onGenerateBook,
  generating,
  bookReady,
  bookId,
}: {
  steps: string[];
  pitfalls: string[];
  onGenerateBook: () => void;
  generating: boolean;
  bookReady: boolean;
  bookId: string | null;
}) {
  return (
    <div className="space-y-3">
      <Card className="space-y-2">
        <CardHeader
          title={
            <span className="flex items-center gap-1.5">
              <Sparkles className="size-3.5 text-accent" aria-hidden />
              下一步建议
            </span>
          }
        />
        {steps.length === 0 ? (
          <p className="text-[11px] text-text-dim">可以换一个相邻的仓库继续，例如同一项目的另一个子包。</p>
        ) : (
          <ul className="space-y-1">
            {steps.map((step) => (
              <li key={step} className="flex items-start gap-1.5 text-[11px] text-text-muted">
                <Check className="mt-0.5 size-3 shrink-0 text-accent" aria-hidden />
                {step}
              </li>
            ))}
          </ul>
        )}
        {pitfalls.length > 0 ? (
          <div className="border-t border-border pt-2">
            <p className="text-[10px] uppercase tracking-wide text-text-dim">常见坑</p>
            <ul className="mt-1 space-y-0.5">
              {pitfalls.map((pitfall) => (
                <li key={pitfall} className="text-[11px] text-warn">
                  · {pitfall}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Card>

      <Card className="space-y-2">
        <CardHeader
          title={
            <span className="flex items-center gap-1.5">
              <BookOpen className="size-3.5 text-accent" aria-hidden />
              生成课程书籍
            </span>
          }
          subtitle="把三层内容整理成可离线阅读的书籍，可导出 PDF。"
        />
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={onGenerateBook}
            loading={generating}
            icon={<BookOpen className="size-3.5" aria-hidden />}
          >
            {generating ? '正在生成…' : '生成课程书籍'}
          </Button>
          {bookId ? (
            <a
              href={`/book/${encodeURIComponent(bookId)}`}
              className="inline-flex h-8 items-center gap-1 rounded-[var(--radius-sm)] border border-border px-2.5 text-[11px] text-text hover:border-accent/50"
            >
              <Download className="size-3" aria-hidden />
              {bookReady ? '打开书籍' : '查看生成进度'}
            </a>
          ) : null}
        </div>
        {!bookId ? (
          <p className="text-[10px] text-text-dim">同一课程再次生成会命中缓存（reused），不会重复花钱。</p>
        ) : null}
      </Card>
    </div>
  );
}

export function RecapEmpty() {
  return <EmptyState title="还没有可复盘的记录" description="先把第一层看完，完课总结会在这里生成。" />;
}

export function RecapBody({ recap }: { recap: RecapResponse }) {
  return (
    <div className="space-y-3">
      <KnowledgeReview points={recap.knowledge_points} />
      <QuizReview stats={recap.quiz_stats} />
    </div>
  );
}
