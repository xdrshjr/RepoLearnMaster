/**
 * First-run guard — spec §3.6.1 rule 1.
 *
 * Pure cookie check, no network call, no timeout: `rl_setup` is written by the
 * BFF on a successful `POST /v1/setup/commit`. Missing cookie + non-whitelisted
 * path → 307 `/setup?next=<path>`.
 *
 * Deliberately NOT a server-component redirect inside layout.tsx: that version
 * (v1 of the spec) both white-screens when the API is down and creates a
 * redirect loop on `/setup` itself. The cookie is a *hint*, never a permission —
 * the API still returns `SETUP_REQUIRED` (428) for writes without an active
 * profile.
 */

import { NextResponse, type NextRequest } from 'next/server';

const SETUP_COOKIE = 'rl_setup';

const WHITELIST_PREFIXES = ['/setup', '/api/', '/_next/', '/favicon'];

function isWhitelisted(pathname: string): boolean {
  if (pathname === '/api' || pathname === '/_next') return true;
  return WHITELIST_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(prefix));
}

export function middleware(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;

  if (request.cookies.get(SETUP_COOKIE)?.value) return NextResponse.next();
  if (isWhitelisted(pathname)) return NextResponse.next();

  const target = request.nextUrl.clone();
  target.pathname = '/setup';
  target.search = `?next=${encodeURIComponent(`${pathname}${search}`)}`;
  // 307 keeps the method and is unambiguous for a "not configured yet" state.
  return NextResponse.redirect(target, 307);
}

export const config = {
  // Exclude static assets from the middleware entirely; the in-code whitelist
  // still guards `/api/*`, `/setup` and `/_next/*`.
  matcher: ['/((?!_next/static|_next/image).*)'],
};
