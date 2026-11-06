'use client';

/**
 * TanStack Query bindings for every endpoint the UI needs (spec §7.5).
 *
 * All queries go through `lib/api/client.ts` → same-origin `/api/*`.
 * staleTime follows the spec: course detail 5 min, lists 60 s, job detail 0.
 */

import {
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
