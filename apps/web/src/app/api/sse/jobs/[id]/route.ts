import type { NextRequest } from 'next/server';

import { proxyEventStream } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Dedicated SSE proxy: `/api/sse/jobs/<id>` → `/v1/jobs/<id>/events`.
 *
 * The response body is the upstream `ReadableStream`, piped as-is. Headers are
 * `text/event-stream`, `Cache-Control: no-cache, no-transform`,
 * `X-Accel-Buffering: no` — any compression or buffering here turns a live
 * progress bar into a 30-second silence (spec §5.5 rule 4).
 */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await context.params;
  return proxyEventStream(request, ['jobs', id, 'events']);
}
