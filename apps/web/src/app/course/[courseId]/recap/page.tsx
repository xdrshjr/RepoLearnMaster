'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Card, Skeleton } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';
import { AbilityRadar } from '@/components/recap/ability-radar';
import {
  CompletionCard,
  KnowledgeReview,
  NextSteps,
  QuizReview,
  RecapEmpty,
} from '@/components/recap/recap-panels';
import { useCourseContext } from '@/components/shell/course-context';
import { isApiError } from '@/lib/api/client';
import { useGenerateBook, useRecap } from '@/lib/api/hooks';
import { courseRoute } from '@/lib/repo/parseRepoUrl';

/**
 * P08 完课总结 — spec §7.2 课程总结.
 *
 * 100% card, knowledge review checklist, quiz review, inline-SVG five-dimension
 * radar (no new dependency), next steps, and the “生成课程书籍” entry (P09).
 */
export default function RecapPage() {
  const router = useRouter();
  const toast = useToast();
  const { courseId, course, completedLessons } = useCourseContext();
  const recap = useRecap(courseId);
  const generateBook = useGenerateBook(courseId);
  const [bookId, setBookId] = useState<string | null>(null);

  const data = recap.data;
  const percent = data?.percent ?? Math.round((completedLessons.size / Math.max(1, course?.lesson_count || 1)) * 100);

  return (
    <div className="space-y-3 p-3">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          {recap.isLoading ? (
            <Skeleton className="h-44" />
          ) : (
            <CompletionCard
              title={course?.title ?? '课程总结'}
              repoFullName={course?.repo.full_name ?? ''}
              percent={percent}
              completed={data?.completed ?? percent >= 100}
              minutes={course?.minutes ?? 0}
              quizStats={data?.quiz_stats ?? {}}
              finishedAt={course?.published_at ?? null}
            />
          )}

          {recap.isError ? (
            <Card className="border-warn/40 bg-warn/5 text-[11px] text-warn">
              复盘数据加载失败：
              {recap.error instanceof Error ? recap.error.message : '未知错误'}
              <button type="button" className="ml-2 underline" onClick={() => void recap.refetch()}>
                重试
              </button>
            </Card>
          ) : null}

          {data ? (
            <>
              <KnowledgeReview points={data.knowledge_points} />
              <QuizReview stats={data.quiz_stats} />
            </>
          ) : recap.isLoading ? null : (
            <RecapEmpty />
          )}
        </div>

        <div className="space-y-3">
          <AbilityRadar scores={data?.ability ?? {}} />
          <NextSteps
            steps={data?.next_steps ?? []}
            pitfalls={data?.pitfalls ?? []}
            generating={generateBook.isPending}
            bookReady={Boolean(bookId)}
            bookId={bookId}
            onGenerateBook={() => {
              generateBook.mutate(
                { preset: 'standard' },
                {
                  onSuccess: (result) => {
                    setBookId(result.book_id);
                    toast.push({
                      tone: result.reused ? 'info' : 'success',
                      title: result.reused ? '命中已有书籍' : '已开始生成书籍',
                      description: result.reused ? '直接打开阅读。' : '生成完成后会在书籍页自动刷新。',
                    });
                    router.push(`/book/${encodeURIComponent(result.book_id)}`);
                  },
                  onError: (error) => {
                    const apiError = isApiError(error) ? error : null;
                    toast.push({
                      tone: 'error',
                      title: apiError ? `${apiError.title} · ${apiError.code}` : '生成书籍失败',
                      description: apiError?.hint ?? error.message,
                      action: apiError?.action,
                    });
                  },
                },
              );
            }}
          />

          <Card className="space-y-2">
            <h3 className="text-xs font-semibold text-text">复盘清单</h3>
            <ul className="space-y-1 text-[11px] text-text-muted">
              <li>· 用一句话说明这个仓库解决什么问题</li>
              <li>· 画出一次请求从入口到输出的调用链</li>
              <li>· 指出你认为最容易出错的一处实现</li>
            </ul>
            <div className="flex gap-2 border-t border-border pt-2">
              <Link
                href={courseRoute(courseId, 'deep-dive')}
                className="text-[11px] text-accent underline underline-offset-2"
              >
                回第三层再看一遍
              </Link>
              <Link href="/" className="text-[11px] text-text-muted underline underline-offset-2">
                换一个仓库
              </Link>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
