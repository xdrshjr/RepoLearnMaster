import type { NextRequest } from 'next/server';

import { proxyRequest } from '@/lib/api/bff';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * `/api/healthz` → `/healthz` (NOT under `/v1`).
 *
 * Used by the `/setup` backend-not-ready view and the settings doctor panel so
 * that "is the API process even up?" is answerable without touching `/v1`.
 */
export async function GET(request: NextRequest): Promise<Response> {
  return proxyRequest(request, { segments: ['healthz'], versioned: false, methods: ['GET'] });
}
