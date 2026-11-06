import type { NextRequest } from 'next/server';

import { proxyRequest } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** `/api/repos/*` → `/v1/repos/*` (resolve a repo URL before creating a course). */
async function handler(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  return proxyRequest(request, { segments: ['repos', ...path] });
}

export const GET = handler;
export const POST = handler;
