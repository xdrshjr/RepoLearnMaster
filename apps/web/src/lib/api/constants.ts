/**
 * Shared header / cookie names. Safe to import from client components — unlike
 * `lib/env.ts`, which holds the server-only API base (spec §7.5).
 */

export const SETUP_COOKIE = 'rl_setup';
export const CSRF_COOKIE = 'rl_csrf';
export const CSRF_HEADER = 'X-CSRF-Token';
export const INTERNAL_TOKEN_HEADER = 'X-Internal-Token';
export const REQUEST_ID_HEADER = 'X-Request-Id';
export const LAST_EVENT_ID_HEADER = 'Last-Event-ID';
