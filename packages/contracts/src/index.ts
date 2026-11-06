/**
 * `@repolearn/contracts` 的入口 —— 前后端唯一契约的**包级**出口（spec §4.3 / §5.5）。
 *
 * 三样东西在这里汇合，缺一样都会有真实后果：
 *
 * 1. `paths` / `components` —— 由 `openapi.json` 生成（`scripts/gen.mjs`）。前端据此
 *    发现"后端少了一个字段"，而不是在运行时靠 `any` 兜住。
 * 2. `EventEnvelope` —— SSE 线格式。它是**跨进程**协议：Kernel 发、API 转发、
 *    浏览器解。三处各写一份类型是这类项目最常见的漂移来源。
 * 3. `ERROR_CODES` —— 与 `apps/api/repolearn/core/errors.py` 一一对应；契约测试
 *    会用这份列表反查后端，新增错误码忘了同步会直接红灯。
 */

export type { components, operations, paths } from './types';

/** SSE 事件的统一信封（spec §5.5）。`seq` 单调递增，断线重连靠 `Last-Event-ID`。 */
export interface EventEnvelope<TData = Record<string, unknown>> {
  /** 信封版本。破坏性变更必须升版本，消费方据此拒收而不是瞎猜。 */
  schemaVersion: 1;
  /** 事件类型，如 `job.phase` / `agent.text.delta` / `run.completed`。 */
  type: string;
  /** 从 1 开始、在同一 run/job 内单调递增。 */
  seq: number;
  /** 毫秒时间戳（服务端时钟）。 */
  ts: number;
  /** 归属的 Job；Kernel 内部 run 为 null。 */
  jobId: string | null;
  /** Kernel 的 run id；API 侧事件为 null。 */
  runId: string | null;
  data: TData;
}

/** 失败事件的附加形状（`run.failed` / `job.failed`）。 */
export interface FailureDetail {
  code: string;
  message: string;
  retryable: boolean;
}

/**
 * 与 `core/errors.py` 的 19 个错误码一一对应。
 *
 * 排序与后端保持一致，便于肉眼 diff；前端专有的 `API_UNREACHABLE`（BFF 自己合成
 * 的传输错误）**不在**这里——它不是后端契约的一部分。
 */
export const ERROR_CODES = [
  'REPO_NOT_FOUND',
  'REPO_FORBIDDEN',
  'RATE_LIMITED',
  'REPO_TOO_LARGE',
  'NO_MODEL_FOR_ROLE',
  'SETUP_REQUIRED',
  'INVALID_KEY',
  'PROVIDER_UNAVAILABLE',
  'BUDGET_EXCEEDED',
  'JOB_NOT_FOUND',
  'JOB_CONFLICT',
  'COURSE_NOT_READY',
  'ANCHOR_STALE',
  'OBJECT_MISSING',
  'INGEST_BLOCKED_PATH',
  'CONTRACT_VIOLATION',
  'IDEMPOTENCY_MISMATCH',
  'PROFILE_CONFLICT',
  'INTERNAL',
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

/** 后端错误体的唯一形状（spec §5.6）。 */
export interface ApiErrorEnvelope {
  error: {
    code: ErrorCode | string;
    message: string;
    hint?: string | null;
    retryable?: boolean;
    req_id?: string;
    details?: Record<string, unknown>;
  };
}

/** `X-API-Version` 的当前值；破坏性变更必须同时升这个数与路径前缀。 */
export const API_VERSION = 1 as const;

/** Kernel 侧工具名的单一来源（`services/agent-kernel/src/runtime.ts` 同源）。 */
export const REPO_TOOL_NAMES = [
  'repo_list_tree',
  'repo_read_file',
  'repo_grep',
  'repo_file_outline',
] as const;

export const EMIT_TOOL_NAMES = ['emit_course_json', 'emit_lesson', 'emit_trace'] as const;
