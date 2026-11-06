/**
 * Server-only runtime configuration — spec §7.5.
 *
 * IMPORTANT: this module must never be imported from a client component. The
 * API base is a server secret: exporting it to the browser would break the
 * same-origin rule (spec §2.2 constraint 6) and silently drop cookies,
 * SameSite protection and SSE buffering control.
 *
 * Client-side code imports header names from `lib/api/constants.ts` instead.
 */

import {
  CSRF_COOKIE,
  CSRF_HEADER,
  INTERNAL_TOKEN_HEADER,
  REQUEST_ID_HEADER,
  SETUP_COOKIE,
} from '@/lib/api/constants';

const DEFAULT_API_BASE = 'http://127.0.0.1:8000';

export function isServer(): boolean {
  return typeof window === 'undefined';
}

/**
 * Runtime assertion for server modules. Called by the BFF helper on every
 * request so an accidental client import fails loudly instead of leaking the
 * internal base URL.
 */
export function assertServerOnly(where: string): void {
  if (!isServer()) {
    throw new Error(
      `lib/env.ts must only be used on the server (imported from ${where}). ` +
        'Client components talk to same-origin /api/* instead.',
    );
  }
}

export function apiBase(): string {
  assertServerOnly('apiBase()');
  const raw = process.env.REPOLEARN_API_BASE ?? DEFAULT_API_BASE;
  return raw.replace(/\/+$/, '');
}

export function internalToken(): string {
  assertServerOnly('internalToken()');
  return process.env.REPOLEARN_INTERNAL_TOKEN ?? '';
}

/** `REPOLEARN_WEB_MOCK=1` short-circuits the BFF with fixtures (E2E / offline demo). */
export function isMockMode(): boolean {
  assertServerOnly('isMockMode()');
  return process.env.REPOLEARN_WEB_MOCK === '1';
}

export { CSRF_COOKIE, CSRF_HEADER, INTERNAL_TOKEN_HEADER, REQUEST_ID_HEADER, SETUP_COOKIE };
