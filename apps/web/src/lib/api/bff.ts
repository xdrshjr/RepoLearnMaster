/**
 * BFF (backend-for-frontend) helper — spec §3.3 / §5.3.
 *
 * Mapping rule: `/api/<x>` → `${API_BASE}/v1/<x>`.
 *
 * Four non-negotiables for every handler built on this module (§3.3):
 *  1. `runtime = 'nodejs'` + `dynamic = 'force-dynamic'` (declared per route);
 *  2. SSE responses carry `no-cache, no-transform`, `text/event-stream`,
 *     `X-Accel-Buffering: no`;
 *  3. bodies are piped with `ReadableStream` passthrough — never `await
 *     res.text()`, which would buffer a 30s stream into one lump;
 *  4. binary responses forward `Range` / `If-None-Match` and return
 *     206/416/304 with `Content-Range` / `Accept-Ranges` / `ETag`.
 *
 * Upstream error bodies are forwarded *unchanged* — the frontend's
 * `lib/api/errors.ts` is the only place allowed to interpret them (§5.6).
 */

import type { NextRequest } from 'next/server';

import { apiBase, internalToken, isMockMode } from '@/lib/env';
import {
  INTERNAL_TOKEN_HEADER,
  REQUEST_ID_HEADER,
  SETUP_COOKIE,
} from '@/lib/api/constants';

/** Request headers worth forwarding to FastAPI. Everything else is dropped. */
const FORWARD_REQUEST_HEADERS = [
  'accept',
  'accept-language',
  'content-type',
  'cookie',
  'x-csrf-token',
  'idempotency-key',
  'x-request-id',
  'range',
  'if-range',
  'if-none-match',
  'if-modified-since',
  'last-event-id',
] as const;

/** Response headers worth surfacing to the browser. */
const FORWARD_RESPONSE_HEADERS = [
  'content-type',
  'content-range',
  'accept-ranges',
  'etag',
  'last-modified',
  'cache-control',
  'expires',
  'x-api-version',
  'x-request-id',
  'retry-after',
  'location',
  'content-disposition',
  'x-ratelimit-limit',
  'x-ratelimit-remaining',
  'x-ratelimit-reset',
] as const;

/** Route Handler 的请求体上限。本产品没有上传接口，2 MB 只是防呆。 */
export const MAX_BODY_BYTES = 2 * 1024 * 1024;

export interface ProxyOptions {
  /** Path segments after `/api/`, already decoded by Next. */
  segments: string[];
  /** Append `/v1` (all public REST except `/healthz`). Default true. */
  versioned?: boolean;
  /** Preserve the incoming query string. Default true. */
  keepSearch?: boolean;
  /** Only proxy these methods; anything else → 405. */
  methods?: string[];
}

export function upstreamUrl(options: ProxyOptions, search = ''): string {
  const prefix = options.versioned === false ? '' : '/v1';
  const path = options.segments
    .filter((segment) => segment.length > 0)
    .map((segment) => encodeURIComponent(segment))
    .join('/');
  const base = `${apiBase()}${prefix}/${path}`;
  return search ? `${base}${search}` : base;
}

function requestId(request: NextRequest): string {
  return request.headers.get(REQUEST_ID_HEADER) ?? `web-${Date.now().toString(36)}`;
}

function buildUpstreamHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  const token = internalToken();
  if (token) headers.set(INTERNAL_TOKEN_HEADER, token);
  headers.set(REQUEST_ID_HEADER, requestId(request));
  return headers;
}

/**
 * Synthetic error for "the FastAPI process is not answering at all". This is
 * *not* an upstream error body (those are forwarded verbatim); it is the BFF's
 * own transport failure, and `/setup` renders its backend-not-ready view from
 * it (spec §3.6.1 rule 3).
 */
export function unreachableResponse(reason: string, status = 503): Response {
  const body = {
    error: {
      code: 'API_UNREACHABLE',
      message: '后端服务未启动或无法连接。',
      hint: '运行 .\\start.ps1 启动三进程，确认 http://127.0.0.1:8000/healthz 返回 ok，然后点重试。',
      retryable: true,
      req_id: `web-${Date.now().toString(36)}`,
      details: { reason },
    },
  };
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
    },
  });
}

function isEventStream(contentType: string | null): boolean {
  return (contentType ?? '').toLowerCase().includes('text/event-stream');
}

function buildResponseHeaders(upstream: Response, wantsStream: boolean): Headers {
  const headers = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) headers.set(name, value);
  }

  const setCookies = upstream.headers.getSetCookie?.() ?? [];
  for (const cookie of setCookies) headers.append('set-cookie', cookie);

  if (wantsStream) {
    headers.set('content-type', 'text/event-stream; charset=utf-8');
    headers.set('cache-control', 'no-cache, no-transform');
    headers.set('connection', 'keep-alive');
    headers.set('x-accel-buffering', 'no');
    // SSE must never be gzip'd end-to-end (§5.5 rule 4).
    headers.delete('content-length');
    headers.delete('content-encoding');
  } else if (!headers.has('cache-control')) {
    headers.set('cache-control', 'no-store');
  }
  return headers;
}

/**
 * Pipes the upstream body straight through. `Response(status, null)` for
 * bodiless statuses (204/304) is required — passing a stream there throws.
 */
function pipeBody(upstream: Response): BodyInit | null {
  if (upstream.status === 204 || upstream.status === 205 || upstream.status === 304) return null;
  return upstream.body ?? null;
}

/** Proxy one request 1:1, preserving status, error body and streaming. */
export async function proxyRequest(request: NextRequest, options: ProxyOptions): Promise<Response> {
  if (options.methods && !options.methods.includes(request.method)) {
    return new Response(
      JSON.stringify({
        error: {
          code: 'INTERNAL',
          message: `不支持的方法 ${request.method}`,
          hint: '这是前端 BFF 的编程错误，请报告。',
          retryable: false,
          req_id: requestId(request),
        },
      }),
      { status: 405, headers: { 'content-type': 'application/json; charset=utf-8' } },
    );
  }

  const search = options.keepSearch === false ? '' : request.nextUrl.search;
  const target = upstreamUrl(options, search);
  const hasBody = request.method !== 'GET' && request.method !== 'HEAD';

  // Route Handler 的内存没有 Next 的 Server Action 限额兜底：不加这一道，
  // 一个几十 MB 的请求体会被整块读进 Node 堆里（`await request.arrayBuffer()`）。
  const declared = Number(request.headers.get('content-length') ?? '0');
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) {
    return new Response(
      JSON.stringify({
        error: {
          code: 'VALIDATION_FAILED',
          message: `请求体过大（${declared} 字节，上限 ${MAX_BODY_BYTES}）`,
          hint: '本产品没有文件上传接口；请确认没有把大文件贴进输入框。',
          retryable: false,
          req_id: requestId(request),
        },
      }),
      { status: 413, headers: { 'content-type': 'application/json; charset=utf-8' } },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: buildUpstreamHeaders(request),
      body: hasBody ? Buffer.from(await request.arrayBuffer()) : undefined,
      redirect: 'manual',
      cache: 'no-store',
      // Node needs this for streamed request bodies; harmless for buffers.
      duplex: hasBody ? 'half' : undefined,
    } as RequestInit & { duplex?: 'half' });
  } catch (error) {
    return unreachableResponse(error instanceof Error ? error.message : 'unknown transport error');
  }

  const wantsStream = isEventStream(upstream.headers.get('content-type'));
  const headers = buildResponseHeaders(upstream, wantsStream);

  // Mock mode is for offline E2E only: it must never mask a real stream shape.
  if (isMockMode() && wantsStream) headers.set('x-repolearn-mock', '1');

  // `/setup/commit` success → write the first-run guard cookie (§3.6.1 rule 1).
  if (isSetupCommitSuccess(request, options, upstream)) {
    const secure = request.nextUrl.protocol === 'https:' ? '; Secure' : '';
    headers.append(
      'set-cookie',
      `${SETUP_COOKIE}=1; HttpOnly; SameSite=Lax; Path=/; Max-Age=31536000${secure}`,
    );
  }

  return new Response(pipeBody(upstream), {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  });
}

function isSetupCommitSuccess(
  request: NextRequest,
  options: ProxyOptions,
  upstream: Response,
): boolean {
  if (request.method !== 'POST') return false;
  if (upstream.status < 200 || upstream.status >= 300) return false;
  const joined = options.segments.join('/');
  return joined === 'setup/commit';
}

/**
 * Binary object proxy (`/api/objects/<kind>/<name>` → `/v1/objects/<kind>/<name>`).
 * Audio seeking and PDF streaming die silently if any of these headers are
 * dropped (§5.3 “对象的 Range/ETag 契约”).
 */
export async function proxyObject(request: NextRequest, segments: string[]): Promise<Response> {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response(null, { status: 405, headers: { allow: 'GET, HEAD' } });
  }

  const target = upstreamUrl({ segments: ['objects', ...segments], versioned: true });
  const headers = buildUpstreamHeaders(request);

  let upstream: Response;
  try {
    upstream = await fetch(target, { method: request.method, headers, redirect: 'manual', cache: 'no-store' });
  } catch (error) {
    return unreachableResponse(error instanceof Error ? error.message : 'unknown transport error');
  }

  const outHeaders = buildResponseHeaders(upstream, false);
  // Always advertise byte ranges, even for 304/416 (§5.3).
  if (!outHeaders.has('accept-ranges')) outHeaders.set('accept-ranges', 'bytes');
  // 对象是**内容寻址**的（键就是内容的 sha256 前缀），因此可以放心长缓存：
  // 上游没给 cache-control 时不能落成 `no-store`，否则拖动一次音频进度条
  // 就要重新下载整个文件。
  if (!upstream.headers.get('cache-control')) {
    outHeaders.set('cache-control', 'private, max-age=3600');
  }
  // 不伪造 ETag：早期实现用 `content-length` 合成 `W/"len-<n>"`，两个等长的
  // 不同文件会共享 ETag，客户端于是拿到 304 和**错误的内容**。
  if (upstream.status === 416 && !outHeaders.has('content-range')) {
    const total = upstream.headers.get('content-length') ?? '*';
    outHeaders.set('content-range', `bytes */${total}`);
  }

  const body = upstream.status === 304 ? null : upstream.body;

  return new Response(body, { status: upstream.status, headers: outHeaders });
}

/** Dedicated SSE proxy: `/api/sse/jobs/<id>` → `/v1/jobs/<id>/events`. */
export async function proxyEventStream(
  request: NextRequest,
  segments: string[],
): Promise<Response> {
  const target = upstreamUrl({ segments, versioned: true });
  const headers = buildUpstreamHeaders(request);
  headers.set('accept', 'text/event-stream');
  headers.set('cache-control', 'no-cache');

  let upstream: Response;
  try {
    upstream = await fetch(target, { method: 'GET', headers, cache: 'no-store' });
  } catch (error) {
    return unreachableResponse(error instanceof Error ? error.message : 'unknown transport error');
  }

  if (!upstream.ok) {
    // Forward the structured error body verbatim (§5.6), with stream headers off.
    const outHeaders = buildResponseHeaders(upstream, false);
    return new Response(upstream.body, { status: upstream.status, headers: outHeaders });
  }

  const outHeaders = buildResponseHeaders(upstream, true);
  return new Response(upstream.body, { status: 200, headers: outHeaders });
}
