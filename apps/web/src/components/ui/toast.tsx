'use client';

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import { cn } from '@/lib/utils';

export type ToastTone = 'info' | 'success' | 'warn' | 'error';

export interface ToastItem {
  id: string;
  tone: ToastTone;
  title: string;
  description?: string;
  /** Actionable next step — the point of the whole error-copy table (§5.6). */
  action?: { label: string; href?: string; onClick?: () => void };
  ttlMs?: number;
}

interface ToastContextValue {
  push: (toast: Omit<ToastItem, 'id'>) => void;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TONE_STYLES: Record<ToastTone, string> = {
  info: 'border-info/40 bg-info/10',
  success: 'border-accent/40 bg-accent-soft',
  warn: 'border-warn/40 bg-warn/10',
  error: 'border-danger/40 bg-danger/10',
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const push = useCallback(
    (toast: Omit<ToastItem, 'id'>) => {
      const id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
      setItems((current) => [...current.slice(-4), { ...toast, id }]);
      const ttl = toast.ttlMs ?? (toast.tone === 'error' ? 9000 : 5000);
      if (typeof window !== 'undefined') {
        window.setTimeout(() => dismiss(id), ttl);
      }
    },
    [dismiss],
  );

  const value = useMemo(() => ({ push, dismiss }), [push, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(92vw,380px)] flex-col gap-2"
      >
        {items.map((item) => (
          <div
            key={item.id}
            role="status"
            className={cn(
              'pointer-events-auto rounded-[var(--radius)] border p-3 text-sm shadow-[var(--shadow-soft)] backdrop-blur',
              TONE_STYLES[item.tone],
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <p className="font-medium text-text">{item.title}</p>
              <button
                type="button"
                onClick={() => dismiss(item.id)}
                aria-label="关闭提示"
                className="text-text-dim hover:text-text"
              >
                ✕
              </button>
            </div>
            {item.description ? (
              <p className="mt-1 text-xs leading-[1.6] text-text-muted">{item.description}</p>
            ) : null}
            {item.action ? (
              item.action.href ? (
                <a
                  href={item.action.href}
                  className="mt-2 inline-block text-xs font-medium text-accent underline underline-offset-2"
                >
                  {item.action.label}
                </a>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    item.action?.onClick?.();
                    dismiss(item.id);
                  }}
                  className="mt-2 text-xs font-medium text-accent underline underline-offset-2"
                >
                  {item.action.label}
                </button>
              )
            ) : null}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    // Toasts are best-effort: a page rendered outside the provider (a unit test)
    // must not crash because of a missing notification.
    return { push: () => undefined, dismiss: () => undefined };
  }
  return context;
}
