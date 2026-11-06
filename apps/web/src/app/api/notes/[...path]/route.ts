import type { NextRequest } from 'next/server';

import { proxyRequest } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** `/api/notes/*` → `/v1/notes/*`. */
async function handler(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  return proxyRequest(request, { segments: ['notes', ...path] });
}

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const DELETE = handler;
