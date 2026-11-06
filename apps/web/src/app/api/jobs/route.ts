import type { NextRequest } from 'next/server';

import { proxyRequest } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * `/api/jobs` (collection) → `/v1/jobs`.
 *
 * Same reason as `api/courses/route.ts`: `[...path]` does not match the bare
 * collection, so the job list (settings → 任务 tab) would 404 without this file.
 */
async function handler(request: NextRequest): Promise<Response> {
  return proxyRequest(request, { segments: ['jobs'] });
}

export const GET = handler;
