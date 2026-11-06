import type { NextRequest } from 'next/server';

import { proxyRequest } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** `/api/metrics` → `/v1/metrics` (aggregate job/cache/provider/learning numbers). */
export async function GET(request: NextRequest): Promise<Response> {
  return proxyRequest(request, { segments: ['metrics'] });
}
