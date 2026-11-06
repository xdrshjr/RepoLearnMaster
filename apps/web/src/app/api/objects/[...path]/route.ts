import type { NextRequest } from 'next/server';

import { proxyObject } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Binary proxy: `/api/objects/<kind>/<name>` → `/v1/objects/<kind>/<name>`.
 *
 * `kind ∈ audio | pdf | diagrams`. Forwards `Range` / `If-None-Match` and
 * passes back 206 / 416 / 304 with `Content-Range`, `Accept-Ranges`, `ETag`
 * (spec §5.3). Without this, dragging the audio scrubber re-downloads the whole
 * file every time.
 */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  return proxyObject(request, path);
}

export async function HEAD(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  return proxyObject(request, path);
}
