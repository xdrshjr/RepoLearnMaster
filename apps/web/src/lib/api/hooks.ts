'use client';

/**
 * TanStack Query bindings for every endpoint the UI needs (spec §7.5).
 *
 * All queries go through `lib/api/client.ts` → same-origin `/api/*`.
 * staleTime follows the spec: course detail 5 min, lists 60 s, job detail 0.
 */

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query';

import { api, newIdempotencyKey, requestSafe, type SafeResult } from '@/lib/api/client';
import type {
  ActivateResponse,
  BookChapterDetail,
  BookCreatedResponse,
  BookDetail,
  CourseCreatedResponse,
  CourseDetail,
  CourseListItem,
  CourseListResponse,
  DoctorResponse,
  FileContentResponse,
  HealthResponse,
  JobDetail,
  JobListResponse,
  LessonListResponse,
  LlmProbeResponse,
  MetricsResponse,
  PdfStatus,
  PlaybackBundle,
  ProfileListResponse,
  ProgressResponse,
  QuestionListResponse,
  QuizAnswerResponse,
  RecapResponse,
  RevisionListResponse,
  RevisionResponse,
  SetupCommitResponse,
  SetupStateResponse,
  TtsProbeResponse,
} from '@/lib/api/types';

export const qk = {
  courses: (params?: Record<string, unknown>) => ['courses', params ?? {}] as const,
  course: (id: string) => ['course', id] as const,
  lessons: (id: string) => ['course', id, 'lessons'] as const,
  playback: (id: string, lessonKey: string) => ['course', id, 'playback', lessonKey] as const,
  file: (id: string, path: string) => ['course', id, 'file', path] as const,
  questions: (id: string, lessonKey?: string) => ['course', id, 'questions', lessonKey ?? 'all'] as const,
  recap: (id: string) => ['course', id, 'recap'] as const,
  job: (id: string) => ['job', id] as const,
  jobs: (params?: Record<string, unknown>) => ['jobs', params ?? {}] as const,
  setupState: () => ['setup', 'state'] as const,
  profiles: () => ['settings', 'profiles'] as const,
  revisions: () => ['settings', 'revisions'] as const,
  doctor: () => ['settings', 'doctor'] as const,
  metrics: () => ['metrics'] as const,
  book: (id: string) => ['book', id] as const,
  bookChapter: (id: string, key: string) => ['book', id, 'chapter', key] as const,
  pdf: (id: string) => ['book', id, 'pdf'] as const,
  health: () => ['health'] as const,
};

/* ------------------------------------------------------------------ courses */

export function useCourses(
  params: { status?: string; limit?: number; cursor?: string; q?: string; owner?: string } = {},
  options: Partial<UseQueryOptions<CourseListResponse>> = {},
) {
  return useQuery<CourseListResponse>({
    queryKey: qk.courses(params),
    queryFn: () => api.get<CourseListResponse>('/api/courses', { query: params }),
    staleTime: 60_000,
    ...options,
  });
}

/* ------------------------------------------------------- search (spec §3.4.4) */

/**
 * 搜索契约的**前端增量部分**。
 *
 * `types.ts` 是手工镜像的 wire 类型，本轮不在我的改动范围内（`schema.d.ts` 由
 * 契约生成、已含这些字段），所以新增的 `mode` / `fallback_reason` / `highlights`
 * 在这里以**扩展**而非重写的方式声明：`CourseListItem` 一个字段都不改，只是多
 * 了一个可选的高亮组，因此老调用点（首页热门课程、最近学习）完全不受影响。
 */
export type HighlightSegment =
  /** 服务端做的是**安全切段**，不返回 HTML——这正是前端不需要 dangerouslySetInnerHTML 的原因。 */
  { text: string; marked: boolean };

export interface HighlightGroup {
  title?: HighlightSegment[] | null;
  summary?: HighlightSegment[] | null;
  repo?: HighlightSegment[] | null;
}

/** 实际生效的检索模式，**不是**配置值（`auto` 只出现在请求侧）。 */
export type SearchMode = 'none' | 'scan' | 'fts' | string;
export type SearchFallbackReason = 'query_too_short' | 'sqlite_too_old' | string | null;

/** `GET /api/courses` 的请求侧模式（`search-parity.spec.ts` 的对照实验也用它）。 */
export type CourseSearchMode = 'auto' | 'scan' | 'fts';

export interface SearchCourseItem extends CourseListItem {
  highlights?: HighlightGroup | null;
}

export interface CourseSearchResponse {
  items: SearchCourseItem[];
  /** `none | scan | fts` —— 回退时如实回显，UI 据此显示"为什么不是全文索引"。 */
  mode: SearchMode;
  fallback_reason?: SearchFallbackReason;
  next_cursor?: string | null;
  /** 只有 fts 模式给（offset 分页，上限 200，见 §3.4.3 第 3 条取舍）。 */
  next_offset?: number | null;
  total?: number | null;
}

/**
 * 课程搜索 —— `staleTime: 0` + `placeholderData: keepPreviousData`（评审 P1-1）。
 *
 * `keepPreviousData` 在 TanStack Query **v5** 里是一个**函数**，必须从包里 import
 * 后传给 `placeholderData`；v4 的 `keepPreviousData: true` 选项在 v5 已移除。
 * 写错的后果是"每次按键列表闪成空态"（或 TS 直接报错），两种都不是我们要的。
 */
export function useCourseSearch(
  q: string,
  mode: CourseSearchMode = 'auto',
  options: Partial<UseQueryOptions<CourseSearchResponse>> = {},
) {
  const term = q.trim();
  return useQuery<CourseSearchResponse>({
    queryKey: qk.courses({ q: term, mode, limit: 20 }),
    queryFn: () =>
      api.get<CourseSearchResponse>('/api/courses', { query: { q: term, mode, limit: 20 } }),
    // 与既有 hooks 同一形态：没有关键词就不发请求（空查询在后端是"全量列表"，
    // 而首页的"热门课程"已经承担了那件事）。
    enabled: term.length > 0,
    staleTime: 0,
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useCourse(courseId: string | null | undefined) {
  return useQuery<CourseDetail>({
    queryKey: qk.course(courseId ?? 'none'),
    queryFn: () => api.get<CourseDetail>(`/api/courses/${encodeURIComponent(courseId!)}`),
    enabled: Boolean(courseId),
    staleTime: 5 * 60_000,
  });
}

export function useCourseLessons(courseId: string | null | undefined) {
  return useQuery<LessonListResponse>({
    queryKey: qk.lessons(courseId ?? 'none'),
    queryFn: () => api.get<LessonListResponse>(`/api/courses/${encodeURIComponent(courseId!)}/lessons`),
    enabled: Boolean(courseId),
    staleTime: 5 * 60_000,
  });
}

export function usePlayback(courseId: string | null | undefined, lessonKey: string | null | undefined) {
  return useQuery<PlaybackBundle>({
    queryKey: qk.playback(courseId ?? 'none', lessonKey ?? 'none'),
    queryFn: () =>
      api.get<PlaybackBundle>(
        `/api/courses/${encodeURIComponent(courseId!)}/lessons/${encodeURIComponent(lessonKey!)}/playback`,
      ),
    enabled: Boolean(courseId && lessonKey),
    staleTime: 5 * 60_000,
  });
}

export function useCourseFile(
  courseId: string | null | undefined,
  path: string | null | undefined,
  enabled = true,
) {
  return useQuery<FileContentResponse>({
    queryKey: qk.file(courseId ?? 'none', path ?? 'none'),
    queryFn: () =>
      api.get<FileContentResponse>(`/api/courses/${encodeURIComponent(courseId!)}/files`, {
        query: { path: path ?? '' },
      }),
    enabled: Boolean(courseId && path && enabled),
    staleTime: 60 * 60_000,
    // File content is immutable for a commit_sha (spec §5.2).
    gcTime: 30 * 60_000,
  });
}

export function useJob(jobId: string | null | undefined) {
  return useQuery<JobDetail>({
    queryKey: qk.job(jobId ?? 'none'),
    queryFn: () => api.get<JobDetail>(`/api/jobs/${encodeURIComponent(jobId!)}`),
    enabled: Boolean(jobId),
    staleTime: 0,
  });
}

export function useJobs(params: { status?: string; kind?: string; limit?: number } = {}) {
  return useQuery<JobListResponse>({
    queryKey: qk.jobs(params),
    queryFn: () => api.get<JobListResponse>('/api/jobs', { query: params }),
    staleTime: 0,
    retry: 0,
  });
}

export function useRecap(courseId: string | null | undefined) {
  return useQuery<RecapResponse>({
    queryKey: qk.recap(courseId ?? 'none'),
    queryFn: () => api.get<RecapResponse>(`/api/courses/${encodeURIComponent(courseId!)}/recap`),
    enabled: Boolean(courseId),
    staleTime: 60_000,
  });
}

export function useQuestions(courseId: string | null | undefined, lessonKey?: string) {
  return useQuery<QuestionListResponse>({
    queryKey: qk.questions(courseId ?? 'none', lessonKey),
    queryFn: () =>
      api.get<QuestionListResponse>(`/api/courses/${encodeURIComponent(courseId!)}/questions`, {
        query: { lesson_key: lessonKey },
      }),
    enabled: Boolean(courseId),
    staleTime: 30_000,
  });
}

/* ------------------------------------------------------------- mutations */

export function useCreateCourse() {
  const queryClient = useQueryClient();
  return useMutation<CourseCreatedResponse, Error, { repoUrl: string; ref?: string | null }>({
    mutationFn: ({ repoUrl, ref }) =>
      api.post<CourseCreatedResponse>(
        '/api/courses',
        { repo_url: repoUrl, ref: ref ?? undefined },
        // Idempotency-Key is mandatory for course creation (§5.1).
        { idempotencyKey: newIdempotencyKey(), timeoutMs: 30_000, retries: 0 },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['courses'] });
    },
  });
}

/* ---------------------------------------------- upgrade (spec §3.5.2 / §3.5.4) */

/**
 * `POST /v1/courses/{id}/upgrade` 的两种成功形态（spec §5.1.2）：
 *
 * * **200 + 计划**：`dry_run=True`，或 `mode in {none, reused}`。纯读，不写库。
 * * **202 + job**：真的开始生成新版本，旧版本**全程保持可读**（与 `/rebuild` 的
 *   关键区别，§3.5.4）。
 *
 * 判别用 `job_id` 是否存在——两条分支的 200 体都带 `course_id`，只有 202 带 `job_id`。
 */
export type UpgradeDecisionMode = 'none' | 'partial' | 'full' | 'reused' | string;

export interface UpgradeAffectedLesson {
  key: string;
  title: string;
}

export interface UpgradePlan {
  mode: UpgradeDecisionMode;
  /** 机器可读 + 人类可读，直接进 UI（阈值、受影响文件数都在这里）。 */
  reasons: string[];
  stats: Record<string, number>;
  affected_lessons: UpgradeAffectedLesson[];
  course_id: string;
  from_sha: string;
  to_sha: string;
}

export interface UpgradeStarted {
  job_id: string;
  course_id: string;
  mode: string;
}

export type UpgradeOutcome =
  | { kind: 'plan'; plan: UpgradePlan }
  | { kind: 'started'; started: UpgradeStarted };

type UpgradeWireResponse = Partial<UpgradePlan> & Partial<UpgradeStarted>;

function readUpgradeOutcome(data: UpgradeWireResponse): UpgradeOutcome {
  if (typeof data.job_id === 'string' && data.job_id.length > 0) {
    return {
      kind: 'started',
      started: {
        job_id: data.job_id,
        course_id: data.course_id ?? '',
        mode: data.mode ?? 'partial',
      },
    };
  }
  return {
    kind: 'plan',
    plan: {
      mode: data.mode ?? 'none',
      reasons: data.reasons ?? [],
      stats: data.stats ?? {},
      affected_lessons: data.affected_lessons ?? [],
      course_id: data.course_id ?? '',
      from_sha: data.from_sha ?? '',
      to_sha: data.to_sha ?? '',
    },
  };
}

/**
 * 检查更新 / 生成新版本。
 *
 * 幂等：`dry_run` 不写库也不带 `Idempotency-Key`（重复点击有服务端的计划缓存兜底）；
 * 真正开始的那一次**带**幂等键，否则连点两下就会建出两个新版本。
 *
 * 超时 30s 而不是默认 15s：后端同步路径的上限是 20s，超过它会自己切 202
 * （§3.5.2 的 P1-10 第 ③ 条），客户端只是给它留出把 202 说完的余量。
 */
export function useUpgrade(courseId: string | null | undefined) {
  const queryClient = useQueryClient();
  return useMutation<UpgradeOutcome, Error, { dryRun: boolean; ref?: string | null }>({
    mutationFn: async ({ dryRun, ref }) => {
      const data = await api.post<UpgradeWireResponse>(
        `/api/courses/${encodeURIComponent(courseId!)}/upgrade`,
        { dry_run: dryRun, ref: ref ?? undefined },
        {
          timeoutMs: 30_000,
          retries: 0,
          idempotencyKey: dryRun ? undefined : newIdempotencyKey(),
        },
      );
      return readUpgradeOutcome(data ?? {});
    },
    onSuccess: (outcome) => {
      // 新版本一定改变课程列表；旧版本的详情也要重取（`upgraded_from` 关系、
      // 以及"新版本已开始生成"的状态位）。
      void queryClient.invalidateQueries({ queryKey: ['courses'] });
      if (courseId) void queryClient.invalidateQueries({ queryKey: qk.course(courseId) });
      if (outcome.kind === 'started') {
        void queryClient.invalidateQueries({ queryKey: ['jobs'] });
        if (outcome.started.course_id) {
          void queryClient.invalidateQueries({ queryKey: qk.course(outcome.started.course_id) });
        }
      }
    },
  });
}

export function useQuizAnswer(courseId: string | null) {
  return useMutation<QuizAnswerResponse, Error, { itemId: string; choiceId: string }>({
    mutationFn: ({ itemId, choiceId }) =>
      api.post<QuizAnswerResponse>(
        `/api/courses/${encodeURIComponent(courseId!)}/quiz/${encodeURIComponent(itemId)}/answer`,
        { choice_id: choiceId },
      ),
  });
}

/* --------------------------------------------------------------- setup */

export function useSetupState(options: { enabled?: boolean } = {}) {
  return useQuery<SetupStateResponse>({
    queryKey: qk.setupState(),
    queryFn: () => api.get<SetupStateResponse>('/api/setup/state'),
    staleTime: 0,
    retry: 0,
    enabled: options.enabled ?? true,
  });
}

/** Probe is a *measurement* endpoint: a failed probe is data, not an exception. */
export function useLlmProbe() {
  return useMutation<
    SafeResult<LlmProbeResponse>,
    Error,
    {
      provider: string;
      protocol: string;
      api_key: string;
      base_url?: string | null;
      org?: string | null;
      model_id?: string | null;
    }
  >({
    mutationFn: (body) =>
      requestSafe<LlmProbeResponse>('/api/setup/llm/probe', {
        method: 'POST',
        body,
        timeoutMs: 30_000,
        retries: 0,
      }),
  });
}

export function useTtsProbe() {
  return useMutation<
    SafeResult<TtsProbeResponse>,
    Error,
    { app_id: string; access_token: string; cluster: string; voice_type: string; text?: string }
  >({
    mutationFn: (body) =>
      requestSafe<TtsProbeResponse>('/api/setup/tts/probe', {
        method: 'POST',
        body: { provider: 'doubao', ...body },
        timeoutMs: 30_000,
        retries: 0,
      }),
  });
}

export function useCommitSetup() {
  return useMutation<SetupCommitResponse, Error, Record<string, unknown>>({
    mutationFn: (body) => api.post<SetupCommitResponse>('/api/setup/commit', body, { retries: 0 }),
  });
}

/* ------------------------------------------------------------- settings */

export function useProfiles() {
  return useQuery<ProfileListResponse>({
    queryKey: qk.profiles(),
    queryFn: () => api.get<ProfileListResponse>('/api/settings/profiles'),
    staleTime: 30_000,
  });
}

export function useActivateProfile() {
  const queryClient = useQueryClient();
  return useMutation<ActivateResponse, Error, string>({
    mutationFn: (id) =>
      api.post<ActivateResponse>(`/api/settings/profiles/${encodeURIComponent(id)}/activate`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
  });
}

export function useUpdateRoles() {
  const queryClient = useQueryClient();
  return useMutation<RevisionResponse, Error, Record<string, string>>({
    mutationFn: (roles) => api.patch<RevisionResponse>('/api/settings/roles', { roles }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
  });
}

export function useRevisions() {
  return useQuery<RevisionListResponse>({
    queryKey: qk.revisions(),
    queryFn: () => api.get<RevisionListResponse>('/api/settings/revisions', { query: { limit: 20 } }),
    staleTime: 30_000,
  });
}

export function useRollbackRevision() {
  const queryClient = useQueryClient();
  return useMutation<RevisionResponse, Error, number>({
    mutationFn: (rev) => api.post<RevisionResponse>(`/api/settings/revisions/${rev}/rollback`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
  });
}

export function useDoctor() {
  return useQuery<DoctorResponse>({
    queryKey: qk.doctor(),
    queryFn: () => api.get<DoctorResponse>('/api/settings/doctor'),
    staleTime: 10_000,
    retry: 0,
  });
}

export function useMetrics() {
  return useQuery<MetricsResponse>({
    queryKey: qk.metrics(),
    queryFn: () => api.get<MetricsResponse>('/api/metrics'),
    staleTime: 30_000,
    retry: 0,
  });
}

export function useHealthz(enabled = true) {
  return useQuery<HealthResponse>({
    queryKey: qk.health(),
    queryFn: () => api.get<HealthResponse>('/api/healthz'),
    staleTime: 10_000,
    retry: 0,
    enabled,
  });
}

/* ----------------------------------------------------------------- books */

export function useBook(bookId: string | null | undefined) {
  return useQuery<BookDetail>({
    queryKey: qk.book(bookId ?? 'none'),
    queryFn: () => api.get<BookDetail>(`/api/books/${encodeURIComponent(bookId!)}`),
    enabled: Boolean(bookId),
    staleTime: 60_000,
  });
}

export function useBookChapter(bookId: string | null | undefined, key: string | null | undefined) {
  return useQuery<BookChapterDetail>({
    queryKey: qk.bookChapter(bookId ?? 'none', key ?? 'none'),
    queryFn: () =>
      api.get<BookChapterDetail>(
        `/api/books/${encodeURIComponent(bookId!)}/chapters/${encodeURIComponent(key!)}`,
      ),
    enabled: Boolean(bookId && key),
    staleTime: 5 * 60_000,
  });
}

export function usePdfStatus(bookId: string | null | undefined, enabled = true) {
  return useQuery<PdfStatus>({
    queryKey: qk.pdf(bookId ?? 'none'),
    queryFn: () => api.get<PdfStatus>(`/api/books/${encodeURIComponent(bookId!)}/pdf`),
    enabled: Boolean(bookId && enabled),
    staleTime: 0,
    retry: 0,
  });
}

export function useGenerateBook(courseId: string | null) {
  return useMutation<BookCreatedResponse, Error, { preset: 'standard' | 'deep'; include_audio?: boolean }>({
    mutationFn: (body) =>
      api.post<BookCreatedResponse>(`/api/courses/${encodeURIComponent(courseId!)}/books`, body, {
        idempotencyKey: newIdempotencyKey(),
      }),
  });
}

export function useCreatePdf(bookId: string | null) {
  return useMutation<{ job_id: string }, Error, { engine?: 'chromium' | 'browser-print' }>({
    mutationFn: (body) =>
      api.post<{ job_id: string }>(`/api/books/${encodeURIComponent(bookId!)}/pdf`, body, {
        idempotencyKey: newIdempotencyKey(),
      }),
  });
}

/* -------------------------------------------------------------- progress */

export function useSaveProgress(courseId: string | null) {
  return useMutation<ProgressResponse, Error, { lesson_key: string; step_index: number; position_ms: number; percent: number }>({
    mutationFn: (body) => api.put<ProgressResponse>(`/api/courses/${encodeURIComponent(courseId!)}/progress`, body),
  });
}
