import type { NextRequest } from 'next/server';

import { proxyRequest } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * `/api/courses` (collection) → `/v1/courses`.
 *
 * WHY THIS FILE EXISTS NEXT TO `[...path]`:
 * a catch-all segment (`[...path]`) requires AT LEAST one segment. `/api/courses`
 * therefore did not match `/api/courses/[...path]` at all and Next answered with
 * the 404 page — which in the browser looks like "the API returned HTML". The two
 * calls that hit this exact path are the most important ones in the product:
 * `GET /api/courses` (home page course list) and `POST /api/courses` (create a
 * course from a repo URL). A catch-all alone is never enough for a REST collection.
 */
async function handler(request: NextRequest): Promise<Response> {
  return proxyRequest(request, { segments: ['courses'] });
}

export const GET = handler;
export const POST = handler;
