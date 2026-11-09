/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * Wire types for the RepoLearn public REST API (spec §5.2).
 *
 * Hand-mirrored from `apps/api/repolearn/schemas/*.py` because the generated
 * `schema.d.ts` (spec §5.7) only lands once `packages/contracts` can export the
 * OpenAPI document. Field names are snake_case on purpose: these are wire
 * shapes, not view models.
 */

export type Iso = string;

/* ------------------------------------------------------------------ repos */

export interface RepoBrief {
  full_name: string;
  owner?: string;
  name?: string;
  description?: string | null;
  stars?: number;
  license?: string | null;
  primary_language?: string | null;
  default_branch?: string;
  html_url?: string | null;
}

export interface CommitBrief {
  sha: string;
  committed_at?: Iso | null;
  file_count?: number;
}

export interface ResolveRepoResponse {
  full_name: string;
  description?: string | null;
  stars?: number;
  license?: string | null;
  default_branch?: string;
  head_sha?: string | null;
  existing_course_id?: string | null;
}

/* ---------------------------------------------------------------- courses */

export interface QualityBrief {
  anchor_coverage: number;
  lesson_completeness: number;
  degraded: boolean;
  anchor_confidence: string;
}

export type CourseStatus =
  | 'queued'
  | 'generating'
  | 'ready'
  | 'partial'
  | 'failed'
  | 'failed_budget'
  | 'cancelled'
  | 'stale'
  | string;

export interface CourseListItem {
  id: string;
  repo: RepoBrief;
  title: string;
  summary: string;
  lesson_count: number;
  minutes: number;
  status: CourseStatus;
  quality: QualityBrief;
  updated_at?: Iso | null;
  cover_palette: string;
}

export interface CourseListResponse {
  items: CourseListItem[];
  next_cursor?: string | null;
}

export type LessonBriefWire = {
  key: string;
  title: string;
  status?: string;
  minutes?: number;
  step_count?: number;
  layer?: string;
  goal?: string | null;
  [k: string]: unknown;
};

export interface SectionBrief {
  key: string;
  title: string;
  minutes: number;
  lessons: LessonBriefWire[];
}

export interface CourseDetail {
  id: string;
  repo: RepoBrief;
  commit: CommitBrief;
  title: string;
  subtitle?: string | null;
  summary_md: string;
  status: CourseStatus;
  language: string;
  lesson_count: number;
  minutes: number;
  sections: SectionBrief[];
  blueprint: Record<string, unknown>;
  quality_report: Record<string, unknown>;
  warnings: Array<Record<string, unknown>>;
  cover_palette: string;
  created_at?: Iso | null;
  published_at?: Iso | null;
}

export interface CourseCreatedResponse {
  course_id: string;
  job_id?: string | null;
  reused?: boolean;
  status_url?: string | null;
}

export interface FileContentResponse {
  path: string;
  lang: string;
  line_count: number;
  content: string;
  truncated: boolean;
}

export interface AnchorItem {
  id: string;
  file: string;
  symbol?: string | null;
  line_start: number;
  line_end: number;
  kind: string;
}

export interface AnchorListResponse {
  items: AnchorItem[];
}

export interface LessonSection {
  key: string;
  title: string;
  minutes: number;
  lessons: LessonBriefWire[];
}

export interface LessonListResponse {
  sections: LessonSection[];
}

/* --------------------------------------------------------------- playback */

export interface FocusRef {
  file: string;
  line_start: number;
  line_end: number;
}

export interface Segment {
  id: string;
  text: string;
  start_ms: number;
  end_ms: number;
  focus?: FocusRef | null;
  board_actions: Array<Record<string, unknown>>;
  subtitle_style: string;
}

export interface AudioRef {
  url: string;
  duration_ms: number;
  voice: string;
}

export interface BoardNode {
  id: string;
  label: string;
  source?: Record<string, unknown> | null;
}

export interface Board {
  kind: string;
  mermaid: string;
  nodes: BoardNode[];
}

export interface CodeNote {
  file: string;
  line: number;
  text: string;
}

export interface QuizChoice {
  id: string;
  text: string;
}

export interface QuizItem {
  id: string;
  stem: string;
  choices: QuizChoice[];
  answer_id: string;
  explanation_md: string;
  evidence: Array<Record<string, unknown>>;
}

export interface StepBundle {
  index: number;
  title: string;
  duration_ms: number;
  timing_source: 'tts' | 'estimated' | string;
  audio?: AudioRef | null;
  segments: Segment[];
  board?: Board | null;
  code_notes: CodeNote[];
  quiz: QuizItem[];
  certainty_legend: Record<string, string>;
}

export interface FileRef {
  path: string;
  content_ref: string;
  lang: string;
  line_count: number;
}

export type Certainty = 'source_fact' | 'static_inference' | 'teaching_simulation';

export interface TraceStep {
  index: number;
  title: string;
  certainty: Certainty | string;
  evidence: Array<Record<string, unknown>>;
  variables: Array<Record<string, unknown>>;
  note?: string | null;
}

export interface Trace {
  id: string;
  steps: TraceStep[];
  certainty_summary: Record<string, unknown>;
}

export interface PlaybackBundle {
  course_id: string;
  commit_sha: string;
  lesson: { key: string; title: string; layer: string; minutes: number };
  steps: StepBundle[];
  files: FileRef[];
  trace?: Trace | null;
  /** 为什么这一课没有配音（TTS 未配置 / 凭据错 / 网关不支持…）。 */
  no_voice_reason?: string | null;
}

export interface LessonDetail {
  key: string;
  title: string;
  layer: string;
  minutes: number;
  goal?: string | null;
  anchors: Array<Record<string, unknown>>;
  steps: Array<Record<string, unknown>>;
  quiz: Array<Record<string, unknown>>;
  files: Array<Record<string, unknown>>;
  trace_key?: string | null;
}

/* ---------------------------------------------------------------- progress */

export interface ProgressResponse {
  progress: number;
  course_percent: number;
}

export interface QuizAnswerResponse {
  correct: boolean;
  explanation_md: string;
  evidence: Array<Record<string, unknown>>;
  replayed: boolean;
}

export interface RecapResponse {
  knowledge_points: Array<Record<string, unknown>>;
  call_chain: Record<string, unknown>;
  pitfalls: string[];
  quiz_stats: Record<string, unknown>;
  next_steps: string[];
  ability: Record<string, number>;
  completed: boolean;
  percent: number;
}

/* -------------------------------------------------------------------- Q&A */

export interface QuestionDetail {
  id: string;
  lesson_id?: string | null;
  file: string;
  line_start: number;
  line_end: number;
  layer: string;
  question: string;
  answer_md: string;
  evidence: Array<Record<string, unknown>>;
  runtime: string;
  created_at?: Iso | null;
}

export interface QuestionListResponse {
  items: QuestionDetail[];
}

/* ------------------------------------------------------------------ books */

export interface BookCreatedResponse {
  book_id: string;
  job_id?: string | null;
  reused?: boolean;
}

export interface ChapterBrief {
  key: string;
  title: string;
  words: number;
}

export interface BookDetail {
  id: string;
  course_version_id: string;
  preset: string;
  status: string;
  title: string;
  chapters: ChapterBrief[];
  toc: Array<Record<string, unknown>>;
  quality: Record<string, unknown>;
  word_count: number;
}

export interface BookBlock {
  type: 'md' | 'code' | 'figure' | 'table' | string;
  text: string;
  lang?: string | null;
  caption?: string | null;
}

export interface BookChapterDetail {
  key: string;
  title: string;
  blocks: BookBlock[];
  source_refs: Array<Record<string, unknown>>;
}

export interface PdfStatus {
  status: string;
  pdf_url?: string | null;
  pages: number;
  bytes: number;
  generated_at?: Iso | null;
  commit_sha: string;
  engine: string;
  print_view_url?: string | null;
  error: Record<string, unknown>;
}

/* ------------------------------------------------------------------- jobs */

export interface JobCost {
  tokens: number;
  usd: number;
}

export interface JobDetail {
  id: string;
  kind: string;
  status: string;
  progress: number;
  node?: string | null;
  message?: string | null;
  course_id?: string | null;
  book_id?: string | null;
  started_at?: Iso | null;
  finished_at?: Iso | null;
  error?: Record<string, unknown> | null;
  cost: JobCost;
  created_at?: Iso | null;
  attempts: number;
}

export interface JobListResponse {
  items: JobDetail[];
  next_cursor?: string | null;
}

export interface MetricsResponse {
  jobs: Record<string, unknown>;
  cache: Record<string, unknown>;
  providers: Record<string, unknown>;
  learning: Record<string, unknown>;
  generated_at?: Iso | null;
}

export interface HealthResponse {
  ok: boolean;
  db: boolean;
  kernel: boolean;
  migration: boolean;
  version: string;
  gates: Record<string, string>;
}

/* ------------------------------------------------------------------ setup */

export type LlmProtocol =
  | 'anthropic_messages'
  | 'anthropic_compatible'
  | 'openai_chat'
  | 'openai_compatible'
  | 'openai_responses'
  | 'google_generate'
  | 'gemini_compatible';

export type RoleName = 'planner' | 'writer' | 'critic' | 'vision' | 'quiz' | 'embed';

export const ROLE_NAMES: RoleName[] = ['planner', 'writer', 'critic', 'vision', 'quiz', 'embed'];

export interface ModelCapability {
  text: boolean;
  vision: boolean;
  audio_in: boolean;
  audio_out: boolean;
  tools: boolean;
  json_mode: boolean;
  streaming: boolean;
  thinking: boolean;
  context_window: number;
  price_in: number;
  price_out: number;
}

export interface ModelItem {
  id: string;
  display_name: string;
  capabilities: ModelCapability;
  context_window: number;
  price: number;
}

export interface ProbeError {
  code: string;
  message: string;
  hint?: string | null;
  retryable: boolean;
}

export interface LlmProbeResponse {
  ok: boolean;
  latency_ms: number;
  models: ModelItem[];
  error?: ProbeError | null;
}

export interface TtsProbeResponse {
  ok: boolean;
  latency_ms: number;
  sample_audio_url?: string | null;
  duration_ms: number;
  error?: ProbeError | null;
}

export interface SetupCommitResponse {
  profile_id: string;
  revision: number;
  warnings: string[];
}

export interface SetupStateResponse {
  required: boolean;
  next_step: number;
  steps_done: number[];
  active_profile?: {
    id: string;
    provider: string;
    protocol: string;
    models: string[];
  } | null;
  kernel: { ok: boolean; runtime: string };
  gates: { g1: string; g2: string; g3: string };
  roles: Record<string, string>;
}

export interface ProfileItem {
  id: string;
  label: string;
  provider: string;
  protocol: string;
  base_url?: string | null;
  model_count: number;
  api_key_last4: string;
  active: boolean;
  last_probe: Record<string, unknown>;
  created_at?: Iso | null;
}

export interface ProfileListResponse {
  items: ProfileItem[];
}

export interface ActivateResponse {
  active_profile_id: string;
  revision: number;
}

export interface RevisionItem {
  id: string;
  rev: number;
  created_at?: Iso | null;
  author: string;
  summary: string;
  changes: string[];
}

export interface RevisionListResponse {
  items: RevisionItem[];
}

export interface RevisionResponse {
  revision: number;
}

export type DoctorStatus = 'ok' | 'degraded' | 'fail' | 'unknown';

export interface DoctorCheck {
  name: string;
  status: DoctorStatus;
  detail: string;
  hint?: string | null;
}

export interface DoctorResponse {
  checks: DoctorCheck[];
}

/* ------------------------------------------------------------- SSE events */

export interface SseEnvelope {
  schemaVersion: number;
  type: string;
  seq: number;
  ts: number;
  jobId?: string | null;
  runId?: string | null;
  data: Record<string, unknown>;
}

/* ----------------------------------------------------------------- helpers */

/** Evidence entries are `{file,line_start,line_end,...}` — read them safely. */
export interface EvidenceView {
  file: string;
  line_start: number;
  line_end: number;
  symbol?: string;
  note?: string;
}

export function toEvidence(entry: Record<string, unknown>): EvidenceView | null {
  const file = typeof entry.file === 'string' ? entry.file : null;
  if (!file) return null;
  const start = Number(entry.line_start ?? entry.line ?? 1);
  const end = Number(entry.line_end ?? entry.line ?? start);
  return {
    file,
    line_start: Number.isFinite(start) ? start : 1,
    line_end: Number.isFinite(end) ? end : Number.isFinite(start) ? start : 1,
    symbol: typeof entry.symbol === 'string' ? entry.symbol : undefined,
    note: typeof entry.note === 'string' ? entry.note : undefined,
  };
}

export function readString(source: Record<string, unknown>, key: string, fallback = ''): string {
  const value = source[key];
  return typeof value === 'string' ? value : fallback;
}

export function readNumber(source: Record<string, unknown>, key: string, fallback = 0): number {
  const value = source[key];
  const num = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(num) ? num : fallback;
}

export function readRecord(
  source: Record<string, unknown>,
  key: string,
): Record<string, unknown> | null {
  const value = source[key];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function readArray(source: Record<string, unknown>, key: string): unknown[] {
  const value = source[key];
  return Array.isArray(value) ? value : [];
}
