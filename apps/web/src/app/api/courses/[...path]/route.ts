import type { NextRequest } from 'next/server';

import { proxyRequest } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * `/api/courses/*` → `/v1/courses/*`.
 *
 * `POST /api/courses/{id}/questions` answers with `text/event-stream`; the
 * helper pipes the body through unbuffered, so the answer panel starts streaming
 * immediately (no `await res.text()` anywhere in this path).
 */
async function handler(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  return proxyRequest(request, { segments: ['courses', ...path] });
}

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const PUT = handler;
export const DELETE = handler;
