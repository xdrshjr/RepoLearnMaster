import type { NextRequest } from 'next/server';

import { proxyRequest } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** `/api/jobs/*` → `/v1/jobs/*` (list, detail, cancel, retry). */
async function handler(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  return proxyRequest(request, { segments: ['jobs', ...path] });
}

export const GET = handler;
export const POST = handler;
