/**
 * The one and only network entry point for the browser (spec §7.5).
 *
 * `baseUrl` is the empty string on purpose: every call is a same-origin
 * `/api/*` request that the Next.js BFF forwards to the FastAPI process. An
 * absolute backend URL here would drop cookies, SameSite protection and SSE
 * buffering control (spec §2.2 constraint 6 / §5.3).
 */

import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/api/constants';
import { errorCopy, isErrorCode, type ErrorCode } from '@/lib/api/errors';

export const API_BASE_URL = '';
export const DEFAULT_TIMEOUT_MS = 15_000;

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface ApiEnvelopeError {
  code: string;
  message: string;
  hint?: string | null;
  retryable?: boolean;
  details?: unknown;
  req_id?: string;
}

export class ApiError extends Error {
  readonly code: ErrorCode | 'NETWORK' | 'TIMEOUT' | 'ABORTED' | 'BAD_RESPONSE';
  readonly status: number;
  readonly hint: string;
  readonly retryable: boolean;
  readonly reqId?: string;
  readonly details?: unknown;
  readonly title: string;
  readonly action?: { label: string; href: string };

  constructor(init: {
    code: ErrorCode | 'NETWORK' | 'TIMEOUT' | 'ABORTED' | 'BAD_RESPONSE';
    status: number;
    message: string;
    hint?: string | null;
    retryable?: boolean;
    reqId?: string;
    details?: unknown;
  }) {
    super(init.message);
    this.name = 'ApiError';
    this.code = init.code;
    this.status = init.status;
    this.details = init.details;
    this.reqId = init.reqId;

    const copy = errorCopy(isErrorCode(init.code) ? init.code : 'INTERNAL');
    this.title = copy.title;
    // The backend message is already user facing (Chinese); prefer it, fall
    // back to our own copy, and always keep an actionable hint.
    this.hint = init.hint?.trim() || copy.hint;
    this.retryable = init.retryable ?? copy.retryable;
    this.action = copy.action;
  }

  get isSetupRequired(): boolean {
    return this.code === 'SETUP_REQUIRED';
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/* ------------------------------------------------------------- CSRF cookie */

/**
 * Double-submit CSRF: the token lives in a *readable* cookie (`rl_csrf`, not
 * HttpOnly) and is echoed in `X-CSRF-Token`. The BFF forwards both upstream;
 * the API compares them. No server round trip is needed to bootstrap it.
 */
export function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const prefix = `${name}=`;
  for (const part of document.cookie.split(';')) {
    const trimmed = part.trim();
    if (trimmed.startsWith(prefix)) return decodeURIComponent(trimmed.slice(prefix.length));
  }
  return null;
}

function randomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `rl-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function ensureCsrfToken(): string {
  const existing = readCookie(CSRF_COOKIE);
  if (existing) return existing;
  const token = randomId();
  if (typeof document !== 'undefined') {
    const secure = typeof location !== 'undefined' && location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = `${CSRF_COOKIE}=${encodeURIComponent(token)}; Path=/; SameSite=Lax${secure}`;
  }
  return token;
}

export function newIdempotencyKey(): string {
  return randomId();
}

/* ---------------------------------------------------------------- requests */

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: HttpMethod;
  body?: unknown;
  query?: Record<string, QueryValue>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Extra idempotent attempts for GET (default 2 → 3 tries total). */
  retries?: number;
  idempotencyKey?: string;
  /** Defaults to true for non-GET methods. */
  csrf?: boolean;
  cache?: RequestCache;
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  const url = `${API_BASE_URL}${normalized}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

function buildHeaders(options: RequestOptions, method: HttpMethod): Headers {
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  const isWrite = method !== 'GET';
  if (isWrite && options.csrf !== false) {
    headers.set(CSRF_HEADER, ensureCsrfToken());
  }
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey);
  return headers;
}

/** Parse `{error:{code,message,hint,retryable,req_id}}` into a typed ApiError. */
async function toApiError(response: Response): Promise<ApiError> {
  // 只读一次 body：`response.json()` 会消费流，之后 `response.clone()` 直接抛
  // TypeError —— 那会让"纯文本错误"分支永远拿不到内容，用户只看到状态码。
  let raw = '';
  try {
    raw = await response.text();
  } catch {
    raw = '';
  }
  let payload: unknown = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = null;
    }
  }

  const envelope =
    payload && typeof payload === 'object' && 'error' in payload
      ? (payload as { error?: Partial<ApiEnvelopeError> }).error
      : null;

  if (envelope && typeof envelope.code === 'string') {
    return new ApiError({
      code: isErrorCode(envelope.code) ? envelope.code : 'INTERNAL',
      status: response.status,
      message: envelope.message || errorCopy(envelope.code).message,
      hint: envelope.hint ?? null,
      retryable: envelope.retryable,
      reqId: envelope.req_id,
      details: envelope.details,
    });
  }

  // Some proxies answer with plain text; never lose the status code.
  const text = payload ? '' : raw.trim();
  return new ApiError({
    code: 'INTERNAL',
    status: response.status,
    message: `请求失败（HTTP ${response.status}）${text ? `：${text.slice(0, 160)}` : ''}`,
  });
}

const RETRY_DELAYS_MS = [250, 750];

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export interface SafeResult<T> {
  data: T | null;
  error: ApiError | null;
}

/**
 * Core request helper. GET is idempotent → retried twice on transport errors
 * and 5xx/`retryable` envelope errors. Writes are never retried automatically:
 * a retried POST without the same Idempotency-Key is a duplicate course job.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const maxRetries = options.retries ?? (method === 'GET' ? 2 : 0);

  let attempt = 0;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    try {
      return await requestOnce<T>(path, options, method);
    } catch (error) {
      const retryable =
        error instanceof ApiError
          ? (error.code === 'NETWORK' || error.code === 'TIMEOUT' || error.status >= 500) &&
            error.retryable
          : false;
      if (!retryable || attempt >= maxRetries) throw error;
      const delay = RETRY_DELAYS_MS[attempt] ?? 750;
      attempt += 1;
      await sleep(delay, options.signal);
    }
  }
}

async function requestOnce<T>(path: string, options: RequestOptions, method: HttpMethod): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const onAbort = () => controller.abort();
  options.signal?.addEventListener('abort', onAbort, { once: true });

  try {
    const response = await fetch(buildUrl(path, options.query), {
      method,
      headers: buildHeaders(options, method),
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
      cache: options.cache ?? 'no-store',
      credentials: 'same-origin',
    });

    if (!response.ok) {
      throw await toApiError(response);
    }

    if (response.status === 204 || response.status === 205) {
      return undefined as T;
    }

    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('json')) {
      const text = await response.text();
      return (text ? (JSON.parse(text) as T) : (undefined as T));
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (timedOut) {
      throw new ApiError({
        code: 'TIMEOUT',
        status: 0,
        message: `请求超时（${Math.round(timeoutMs / 1000)} 秒）。`,
        hint: '后端可能正在冷启动或卡住：确认 http://127.0.0.1:8000/healthz 是否正常，然后重试。',
        retryable: true,
      });
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError({ code: 'ABORTED', status: 0, message: '请求已取消。', retryable: false });
    }
    throw new ApiError({
      code: 'NETWORK',
      status: 0,
      message: '无法连接到 RepoLearn 服务。',
      hint: '确认后端已启动（127.0.0.1:8000），再点重试。',
      retryable: true,
    });
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', onAbort);
  }
}

/** Like `request`, but returns `{data, error}` — for probe-style "failure is data". */
export async function requestSafe<T>(
  path: string,
  options: RequestOptions = {},
): Promise<SafeResult<T>> {
  try {
    return { data: await request<T>(path, options), error: null };
  } catch (error) {
    if (error instanceof ApiError) return { data: null, error };
    throw error;
  }
}

export const api = {
  get: <T>(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  del: <T>(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    request<T>(path, { ...options, method: 'DELETE' }),
  safe: requestSafe,
};

export interface StreamRequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  lastEventId?: string | number | null;
}

/**
 * Opens a same-origin event stream with `fetch` (never `EventSource`, which
 * cannot send `X-CSRF-Token` or a reliable `Last-Event-ID`, spec §7.5).
 * Returns the raw `Response` so callers can read the body incrementally.
 */
export async function openEventStream(
  path: string,
  options: StreamRequestOptions = {},
): Promise<Response> {
  const method = options.method ?? 'GET';
  const headers = buildHeaders({ ...options, body: options.body }, method);
  headers.set('Accept', 'text/event-stream');
  if (options.lastEventId !== undefined && options.lastEventId !== null) {
    headers.set('Last-Event-ID', String(options.lastEventId));
  }

  const response = await fetch(buildUrl(path), {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
    cache: 'no-store',
    credentials: 'same-origin',
  });

  if (!response.ok) throw await toApiError(response);
  return response;
}
