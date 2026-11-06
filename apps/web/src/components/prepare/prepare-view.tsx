'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { ArrowRight, GitBranch, RefreshCcw, TriangleAlert } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { Badge, Card, EmptyState, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/toast';
import { CourseBlueprint, QualityPanel } from '@/components/prepare/course-blueprint';
import { PrepareProgress } from '@/components/prepare/prepare-progress';
import { api, isApiError } from '@/lib/api/client';
import { useCourse, useCourses, useCreateCourse, useJob, useJobs } from '@/lib/api/hooks';
import type { JobDetail } from '@/lib/api/types';
import { formatCount, formatMinutes, formatRelativeTime } from '@/lib/format';
import {
  initialPrepareState,
  reducePrepareEvent,
  stateFromJobSnapshot,
  type PrepareState,
} from '@/lib/jobs/prepare-state';
import { courseRoute } from '@/lib/repo/parseRepoUrl';
import { useEventStream } from '@/lib/sse/useEventStream';

const ACTIVE_STATUSES = new Set(['queued', 'generating', 'running', 'cancelling', 'pending']);

export function PrepareView({ owner, name }: { owner: string; name: string }) {
  const searchParams = useSearchParams();
  const toast = useToast();
  const [state, setState] = useState<PrepareState>(initialPrepareState);
  const [cancelling, setCancelling] = useState(false);
  const [jobId, setJobId] = useState<string | null>(searchParams.get('job'));

  const fullName = `${decodeURIComponent(owner)}/${decodeURIComponent(name)}`;
  const repoUrl = `https://github.com/${fullName}`;

  // Find the course version for this repo (same repo can have several versions).
  const coursesQuery = useCourses({ q: fullName, limit: 20 });
  const course = useMemo(() => {
    const items = coursesQuery.data?.items ?? [];
    return (
      items.find((item) => item.repo.full_name.toLowerCase() === fullName.toLowerCase()) ??
      items.find((item) => item.repo.full_name.toLowerCase().endsWith(`/${decodeURIComponent(name).toLowerCase()}`)) ??
      null
    );
  }, [coursesQuery.data, fullName, name]);

  const courseDetail = useCourse(course?.id);
  const jobsQuery = useJobs({ limit: 20 });

  // If we arrived without ?job=, recover the active job from the job list.
  useEffect(() => {
    if (jobId || !course) return;
    const items = jobsQuery.data?.items ?? [];
    const active = items.find(
      (job) => job.course_id === course.id && ACTIVE_STATUSES.has(job.status),
    );
    if (active) setJobId(active.id);
  }, [jobId, course, jobsQuery.data]);

  const jobQuery = useJob(jobId);
  const createCourse = useCreateCourse();

  const stream = useEventStream({
    url: jobId ? `/api/sse/jobs/${encodeURIComponent(jobId)}` : null,
    jobId: jobId ?? undefined,
    snapshotUrl: jobId ? `/api/jobs/${encodeURIComponent(jobId)}` : null,
    enabled: Boolean(jobId) && !state.completed,
    onEvent: (event) => setState((current) => reducePrepareEvent(current, event)),
    onSnapshot: (snapshot) => {
      const job = snapshot as JobDetail;
      if (job && typeof job === 'object') {
        setState((current) => stateFromJobSnapshot(current, job));
      }
    },
  });

  // Seed from the job snapshot as soon as it exists (first paint before SSE).
  useEffect(() => {
    if (jobQuery.data) setState((current) => stateFromJobSnapshot(current, jobQuery.data));
  }, [jobQuery.data]);

  // A finished job means the course detail needs a refetch.
  useEffect(() => {
    if (state.completed) {
      void coursesQuery.refetch();
      void courseDetail.refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.completed]);

  const startGeneration = useCallback(() => {
    createCourse.mutate(
      { repoUrl },
      {
        onSuccess: (data) => {
          if (data.job_id) setJobId(data.job_id);
          toast.push({
            tone: 'info',
            title: data.reused ? '命中已有课程' : '已开始生成',
            description: data.reused ? '这个 commit 已有课程，正在打开。' : '生成大约需要 6–12 分钟。',
          });
        },
        onError: (error) => {
          const apiError = isApiError(error) ? error : null;
          toast.push({
            tone: 'error',
            title: apiError ? `${apiError.title} · ${apiError.code}` : '发起生成失败',
            description: apiError?.hint ?? error.message,
            action: apiError?.action,
          });
        },
      },
    );
  }, [createCourse, repoUrl, toast]);

  const cancelJob = useCallback(async () => {
    if (!jobId) return;
    setCancelling(true);
    try {
      await api.post(`/api/jobs/${encodeURIComponent(jobId)}/cancel`);
      toast.push({ tone: 'info', title: '已请求取消', description: '任务会在几秒内停止。' });
      await jobQuery.refetch();
    } catch (error) {
      const apiError = isApiError(error) ? error : null;
      toast.push({
        tone: 'error',
        title: apiError ? `${apiError.title}` : '取消失败',
        description: apiError?.hint ?? '请稍后重试。',
      });
    } finally {
      setCancelling(false);
    }
  }, [jobId, jobQuery, toast]);

  const rebuild = useCallback(async () => {
    if (!course) return;
    try {
      const result = await api.post<{ job_id: string }>(`/api/courses/${encodeURIComponent(course.id)}/rebuild`, {
        reason: 'user',
        from: 'curriculum',
      });
      if (result?.job_id) setJobId(result.job_id);
      setState(initialPrepareState);
      toast.push({ tone: 'info', title: '已重新排队', description: '会复用已生成的缓存内容。' });
    } catch (error) {
      const apiError = isApiError(error) ? error : null;
      toast.push({ tone: 'error', title: '重建失败', description: apiError?.hint ?? '请重试。' });
    }
  }, [course, toast]);

  const status = jobQuery.data?.status ?? course?.status ?? 'unknown';
  const isReady = course?.status === 'ready' || course?.status === 'partial' || state.completed;
  const isLoading = coursesQuery.isLoading || (Boolean(jobId) && jobQuery.isLoading && !state.completed);

  return (
    <main id="main" className="mx-auto w-full max-w-[1100px] space-y-4 px-4 py-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <GitBranch className="size-4 text-text-dim" aria-hidden />
            <h1 className="truncate text-lg font-semibold text-text">{fullName}</h1>
            <Badge
              tone={isReady ? 'accent' : state.error ? 'danger' : 'warn'}
              className="shrink-0"
            >
              {isReady ? '课程可学习' : state.error ? '生成失败' : '生成中'}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-text-muted">
            {courseDetail.data?.repo.description ?? course?.summary ?? '正在解析仓库信息…'}
            {course?.repo.stars ? ` · ★ ${formatCount(course.repo.stars)}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              void coursesQuery.refetch();
              void jobQuery.refetch();
            }}
            icon={<RefreshCcw className="size-3.5" aria-hidden />}
          >
            刷新
          </Button>
          {isReady && course ? (
            <Link
              href={courseRoute(course.id, 'overview')}
              className="inline-flex h-10 items-center gap-2 rounded-[var(--radius-sm)] bg-accent px-4 text-sm font-semibold text-[#06110c] transition-colors hover:bg-accent-strong"
            >
              开始学习
              <ArrowRight className="size-4" aria-hidden />
            </Link>
          ) : null}
        </div>
      </header>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-40" />
          <Skeleton className="h-28" />
        </div>
      ) : null}

      {!isLoading && !course && !jobId ? (
        <EmptyState
          title="还没有这门课"
          description={`${fullName} 还没有生成过课程。生成大约需要 6–12 分钟，过程中可以离开页面（进度会续传）。`}
          action={
            <Button variant="primary" onClick={startGeneration} loading={createCourse.isPending}>
              生成课程
            </Button>
          }
        />
      ) : null}

      {course || jobId ? (
        <>
          <PrepareProgress
            state={state}
            sseStatus={stream.status}
            jobStatus={status}
            cost={jobQuery.data?.cost}
            onCancel={jobId ? cancelJob : undefined}
            cancelling={cancelling}
          />

          {state.error ? (
            <Card className="border-danger/40 bg-danger/5">
              <div className="flex items-start gap-2">
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-danger">
                    生成失败 · {state.error.code}
                  </p>
                  <p className="mt-1 text-xs text-text-muted">{state.error.message}</p>
                  <p className="mt-1 text-[11px] text-text-dim">
                    已生成的课时仍然可以学习。可以重新发起生成（会复用缓存），或到设置里检查模型与预算。
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={rebuild} loading={createCourse.isPending}>
                      重新生成
                    </Button>
                    <Link
                      href="/settings#doctor"
                      className="inline-flex h-8 items-center rounded-[var(--radius-sm)] px-2 text-[11px] text-accent underline underline-offset-2"
                    >
                      打开诊断面板
                    </Link>
                  </div>
                </div>
              </div>
            </Card>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <CourseBlueprint
              blueprint={courseDetail.data?.blueprint ?? {}}
              sections={courseDetail.data?.sections ?? []}
            />
            <QualityPanel report={courseDetail.data?.quality_report ?? {}} />
          </div>

          {courseDetail.data?.warnings && courseDetail.data.warnings.length > 0 ? (
            <Card>
              <h2 className="text-xs font-semibold text-text">告警（{courseDetail.data.warnings.length}）</h2>
              <ul className="mt-2 space-y-1">
                {courseDetail.data.warnings.slice(0, 6).map((warning, index) => (
                  <li key={index} className="text-[11px] leading-[1.6] text-text-muted">
                    · {String((warning as { message?: string }).message ?? JSON.stringify(warning)).slice(0, 240)}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-text-dim">
            <span>
              {courseDetail.data?.commit?.sha
                ? `commit ${courseDetail.data.commit.sha.slice(0, 8)} · ${formatCount(courseDetail.data.commit.file_count ?? 0)} 个文件`
                : '正在读取 commit 信息'}
              {course?.minutes ? ` · 预计 ${formatMinutes(course.minutes)}` : ''}
            </span>
            <span>{course?.updated_at ? `${formatRelativeTime(course.updated_at)}更新` : null}</span>
          </div>
        </>
      ) : null}
    </main>
  );
}
