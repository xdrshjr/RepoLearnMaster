'use client';

/**
 * 「检查更新」横幅（spec §3.5.4 / §4.4 #69）。
 *
 * **这一步刻意不叫"重新生成"**：`/rebuild` 是"同一个 commit、对内容不满意，从
 * 某阶段起重跑"，而这里做的是"仓库有**新** commit，只重讲被改动文件涉及的课时，
 * 其余复制，旧版本原样保留"。两个按钮长得一样、文案一样，就一定会被用混。
 *
 * 交互顺序（与后端 `dry_run` 的三道闸对应，§3.5.2 P1-10）：
 *   1. 点「检查更新」→ `POST …/upgrade {dry_run:true}` → 200 计划（**不写库**）；
 *   2. 底部抽屉列出受影响课时（可点进对应课时）+ 成本提示（只重讲 N 个）；
 *   3. 主按钮「生成新版本（仅重讲 N 个课时）」→ `{dry_run:false}` → 202 `{job_id}`；
 *   4. `full` 模式必须**二次确认**：它会重建大纲、全部课时重新生成。
 */

import Link from 'next/link';
import { AlertTriangle, CheckCircle2, RefreshCw, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Overlay } from '@/components/ui/overlay';
import { isApiError } from '@/lib/api/client';
import { useCourse, useUpgrade, type UpgradePlan } from '@/lib/api/hooks';
import { courseRoute, repoRoute } from '@/lib/repo/parseRepoUrl';

function shortSha(sha: string | undefined | null): string {
  return sha ? sha.slice(0, 8) : 'unknown';
}

function StatRow({ stats }: { stats: Record<string, number> }) {
  const entries: Array<[string, string]> = [
    ['files_added', '新增文件'],
    ['files_modified', '修改文件'],
    ['files_removed', '删除文件'],
    ['lessons_total', '课时总数'],
  ];
  const visible = entries.filter(([key]) => typeof stats[key] === 'number');
  if (visible.length === 0) return null;
  return (
    <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
      {visible.map(([key, label]) => (
        <div key={key} className="rounded-[var(--radius-sm)] border border-border bg-surface-2/60 px-2 py-1.5">
          <dt className="text-text-dim">{label}</dt>
          <dd className="mt-0.5 text-xs text-text">{stats[key]}</dd>
        </div>
      ))}
    </dl>
  );
}

export function UpdateBanner({ courseId }: { courseId: string }) {
  const upgrade = useUpgrade(courseId);
  const course = useCourse(courseId);

  const [plan, setPlan] = useState<UpgradePlan | null>(null);
  const [open, setOpen] = useState(false);
  const [confirmFull, setConfirmFull] = useState(false);
  const [checking, setChecking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [started, setStarted] = useState<{ job_id: string; course_id: string } | null>(null);
  const [error, setError] = useState<Error | null>(null);

  /** 进度页需要 `owner/name`（准备页路由）；课程详情通常已在缓存里，不会多发请求。 */
  const repo = useMemo(() => {
    const [owner, name] = (course.data?.repo.full_name ?? '').split('/');
    return owner && name ? { owner, name } : null;
  }, [course.data?.repo.full_name]);

  const jobHref = useMemo(() => {
    if (!started) return null;
    return repo ? repoRoute(repo, started.job_id) : courseRoute(started.course_id || courseId, 'overview');
  }, [courseId, repo, started]);

  const check = () => {
    setError(null);
    setChecking(true);
    setConfirmFull(false);
    upgrade.mutate(
      { dryRun: true },
      {
        onSuccess: (outcome) => {
          setChecking(false);
          if (outcome.kind === 'started') {
            // 后端 20s 预算用尽时会直接 202，此时没有计划可看。
            setStarted({ job_id: outcome.started.job_id, course_id: outcome.started.course_id });
            setOpen(false);
            return;
          }
          setPlan(outcome.plan);
          setOpen(true);
        },
        onError: (err) => {
          setChecking(false);
          setError(err);
        },
      },
    );
  };

  const start = () => {
    setError(null);
    setStarting(true);
    upgrade.mutate(
      { dryRun: false },
      {
        onSuccess: (outcome) => {
          setStarting(false);
          if (outcome.kind === 'started') {
            setStarted({ job_id: outcome.started.job_id, course_id: outcome.started.course_id });
            setPlan(null);
            setOpen(false);
            return;
          }
          // 200 → `none` / `reused`：没有新版本可建（或已存在同一份内容）。
          setPlan(outcome.plan);
        },
        onError: (err) => {
          setStarting(false);
          setError(err);
        },
      },
    );
  };

  const close = () => {
    setOpen(false);
    setConfirmFull(false);
    setError(null);
  };

  const affected = plan?.affected_lessons ?? [];
  const lessonHref = (key: string) =>
    `${courseRoute(courseId, 'overview')}?lesson=${encodeURIComponent(key)}`;

  const conflictJobId =
    isApiError(error) && error.code === 'JOB_CONFLICT'
      ? (error.details as { job_id?: string } | undefined)?.job_id
      : undefined;

  return (
    <>
      <div className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-border bg-bg-elevated px-3 py-1.5 text-[11px]">
        <span className="text-text-muted">仓库有新的 commit？</span>
        <Button
          variant="outline"
          size="sm"
          className="h-6 px-2 text-[11px]"
          onClick={check}
          loading={checking}
          icon={checking ? undefined : <RefreshCw className="size-3" aria-hidden />}
        >
          检查更新
        </Button>
        <span className="text-text-dim">只重讲被改动文件涉及的课时，旧版本保持可读</span>

        <span role="status" aria-live="polite" className="text-text-muted">
          {checking ? '正在检查更新…' : ''}
          {starting ? '正在生成新版本…' : ''}
          {started ? '正在生成新版本…' : ''}
        </span>

        {started && jobHref ? (
          <Link
            href={jobHref}
            className="text-accent underline underline-offset-2"
            data-testid="update-banner-job-link"
          >
            查看生成进度
          </Link>
        ) : null}

        {error && !open ? (
          <span className="flex flex-wrap items-center gap-1 text-danger">
            <AlertTriangle className="size-3" aria-hidden />
            {isApiError(error) ? `${error.title}：${error.hint}` : error.message}
            {conflictJobId ? (
              <Link
                href={repo ? repoRoute(repo, conflictJobId) : courseRoute(courseId, 'overview')}
                className="underline underline-offset-2"
              >
                查看已有任务
              </Link>
            ) : null}
          </span>
        ) : null}
      </div>

      <Overlay
        open={open}
        onClose={close}
        variant="bottom"
        title="检查更新"
        description={
          plan ? `${shortSha(plan.from_sha)} → ${shortSha(plan.to_sha)}` : '仓库有新提交时的增量升级'
        }
        footer={
          plan ? (
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={close}>
                取消
              </Button>
              {plan.mode === 'none' || plan.mode === 'reused' ? (
                <Button variant="secondary" size="sm" onClick={close}>
                  知道了
                </Button>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={start}
                  loading={starting}
                  disabled={
                    starting ||
                    (plan.mode === 'full' && !confirmFull) ||
                    (plan.mode === 'partial' && affected.length === 0)
                  }
                  icon={<Sparkles className="size-3" aria-hidden />}
                >
                  {plan.mode === 'full'
                    ? '生成新版本（全部重新生成）'
                    : `生成新版本（仅重讲 ${affected.length} 个课时）`}
                </Button>
              )}
            </div>
          ) : null
        }
      >
        {plan ? (
          <div className="space-y-3 text-xs">
            {plan.mode === 'none' ? (
              <p className="flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-accent/30 bg-accent-soft px-3 py-2 text-accent">
                <CheckCircle2 className="size-3.5 shrink-0" aria-hidden />
                已是最新（{shortSha(plan.to_sha)}）
              </p>
            ) : null}

            {plan.mode === 'partial' ? (
              <p className="rounded-[var(--radius-sm)] border border-warn/40 bg-warn/10 px-3 py-2 text-warn">
                部分更新：只重讲 {affected.length} 个课时，其余课时原样复制（不额外消耗预算）。
              </p>
            ) : null}

            {plan.mode === 'full' ? (
              <div className="rounded-[var(--radius-sm)] border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
                <p className="flex items-center gap-1.5">
                  <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
                  大纲将重建，全部课时重新生成。
                </p>
                <p className="mt-1 text-[11px] text-text-muted">
                  旧版本会原样保留，学习进度会迁移到新版本；但这一次的耗时与成本接近重新导入。
                </p>
              </div>
            ) : null}

            {plan.mode === 'reused' ? (
              <p className="rounded-[var(--radius-sm)] border border-accent/30 bg-accent-soft px-3 py-2 text-accent">
                同一份内容已经生成过课程，直接复用（{plan.course_id}）。
              </p>
            ) : null}

            <StatRow stats={plan.stats} />

            {affected.length > 0 ? (
              <div>
                <p className="mb-1 text-[11px] text-text-dim">受影响的课时（点开查看当前内容）</p>
                <ul className="divide-y divide-border overflow-hidden rounded-[var(--radius-sm)] border border-border">
                  {affected.map((lesson) => (
                    <li key={lesson.key}>
                      <Link
                        href={lessonHref(lesson.key)}
                        className="flex items-center gap-2 px-3 py-2 transition-colors hover:bg-surface-2"
                      >
                        <span className="shrink-0 text-[11px] text-text-dim">{lesson.key}</span>
                        <span className="min-w-0 flex-1 truncate text-text">{lesson.title}</span>
                        <span className="shrink-0 text-[11px] text-accent">打开 →</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {plan.reasons.length > 0 ? (
              <div className="text-[11px] text-text-muted">
                <p className="text-text-dim">判定依据</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4">
                  {plan.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {plan.mode === 'full' ? (
              <label className="flex items-start gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-2/60 px-3 py-2 text-[11px] text-text-muted">
                <input
                  type="checkbox"
                  checked={confirmFull}
                  onChange={(event) => setConfirmFull(event.target.checked)}
                  className="mt-0.5 size-3.5 accent-[var(--color-accent)]"
                />
                我已了解：这次会重建大纲、全部课时重新生成（不是只重讲改动的课时）。
              </label>
            ) : null}

            {error ? (
              <p className="text-[11px] text-danger">
                {isApiError(error) ? `${error.title}：${error.hint}` : error.message}
                {conflictJobId ? (
                  <>
                    {' '}
                    <Link
                      href={repo ? repoRoute(repo, conflictJobId) : courseRoute(courseId, 'overview')}
                      className="text-accent underline underline-offset-2"
                    >
                      查看已有任务
                    </Link>
                  </>
                ) : null}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-text-muted">正在读取更新计划…</p>
        )}
      </Overlay>
    </>
  );
}
