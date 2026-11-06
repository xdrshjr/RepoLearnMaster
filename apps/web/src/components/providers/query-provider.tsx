'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

/**
 * TanStack Query provider — spec §7.5.
 *
 * staleTime per data class: course detail 5 min, lists 60 s, job detail 0.
 * Retries are conservative: the BFF already retries idempotent GETs twice, and
 * a course job must never be re-POSTed automatically.
 */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60_000,
            gcTime: 5 * 60_000,
            retry: (failureCount, error) => {
              if (failureCount >= 1) return false;
              const status =
                typeof error === 'object' && error !== null && 'status' in error
                  ? Number((error as { status: unknown }).status)
                  : 0;
              // 4xx are decisions, not glitches — do not retry them.
              return status === 0 || status >= 500;
            },
            refetchOnWindowFocus: false,
          },
          mutations: { retry: false },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
