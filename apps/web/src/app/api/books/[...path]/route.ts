import type { NextRequest } from 'next/server';

import { proxyRequest } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** `/api/books/*` → `/v1/books/*`. */
async function handler(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  return proxyRequest(request, { segments: ['books', ...path] });
}

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const DELETE = handler;
