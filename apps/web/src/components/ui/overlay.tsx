'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/lib/utils';

export type OverlayVariant = 'dialog' | 'sheet' | 'bottom';

export interface OverlayProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  variant?: OverlayVariant;
  className?: string;
}

/**
 * Dialog / side sheet / bottom panel.
 *
 * Accessibility: `role="dialog"`, `aria-modal`, Escape closes, focus moves into
 * the panel on open and returns to the trigger on close (§7.6 “所有面板可键盘到达”).
 */
export function Overlay({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  variant = 'dialog',
  className,
}: OverlayProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    panel?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      // `aria-modal="true"` 只是**声明**，不做事。没有这个循环，Tab 会走到
      // 遮罩下面的页面里去：键盘用户会"看不见自己把焦点放到哪了"，然后误触
      // 背后的按钮（spec §7.6 要求面板内焦点自洽）。
      const panel = panelRef.current;
      if (!panel) return;
      const focusables = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.offsetParent !== null);
      if (focusables.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (!event.shiftKey && (active === last || active === panel)) {
        event.preventDefault();
        first?.focus();
      } else if (event.shiftKey && (active === first || active === panel)) {
        event.preventDefault();
        last?.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open || typeof document === 'undefined') return null;

  const panelClasses =
    variant === 'dialog'
      ? 'mx-auto mt-[8vh] w-[min(92vw,560px)] rounded-[var(--radius-lg)]'
      : variant === 'sheet'
        ? 'ml-auto h-full w-[min(92vw,520px)] rounded-l-[var(--radius-lg)]'
        : 'mx-auto mb-0 mt-auto w-full max-w-[720px] rounded-t-[var(--radius-lg)]';

  return createPortal(
    <div className="fixed inset-0 z-50 flex bg-black/60 backdrop-blur-sm" onMouseDown={onClose}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : '面板'}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
        className={cn(
          'flex max-h-[92vh] flex-col border border-border bg-surface shadow-[var(--shadow-soft)] outline-none',
          panelClasses,
          className,
        )}
      >
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-text">{title}</h2>
            {description ? <p className="mt-1 text-xs text-text-muted">{description}</p> : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="rounded-[var(--radius-sm)] px-2 py-1 text-text-dim hover:bg-surface-2 hover:text-text"
          >
            ✕
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
        {footer ? <footer className="border-t border-border px-4 py-3">{footer}</footer> : null}
      </div>
    </div>,
    document.body,
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  className,
  ariaLabel,
}: {
  tabs: Array<{ value: T; label: ReactNode; badge?: ReactNode }>;
  value: T;
  onChange: (value: T) => void;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <div role="tablist" aria-label={ariaLabel ?? '选项'} className={cn('flex gap-1 border-b border-border', className)}>
      {tabs.map((tab) => {
        const active = tab.value === value;
        return (
          <button
            key={tab.value}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(tab.value)}
            className={cn(
              '-mb-px border-b-2 px-3 py-2 text-xs transition-colors',
              active
                ? 'border-accent text-text'
                : 'border-transparent text-text-muted hover:text-text',
            )}
          >
            {tab.label}
            {tab.badge ? <span className="ml-1.5 text-text-dim">{tab.badge}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
