import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/utils';

export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'rounded-[var(--radius)] border border-border bg-surface p-4',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export interface CardHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function CardHeader({ title, subtitle, action, className }: CardHeaderProps) {
  return (
    <div className={cn('mb-3 flex items-start justify-between gap-3', className)}>
      <div className="min-w-0">
        <h3 className="truncate text-sm font-semibold text-text">{title}</h3>
        {subtitle ? <p className="mt-1 text-xs text-text-muted">{subtitle}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-base font-semibold text-text">{children}</h2>
      {hint ? <span className="text-xs text-text-dim">{hint}</span> : null}
    </div>
  );
}

export type BadgeTone = 'neutral' | 'accent' | 'warn' | 'danger' | 'info' | 'muted';

const TONES: Record<BadgeTone, string> = {
  neutral: 'bg-surface-2 text-text-muted border-border',
  accent: 'bg-accent-soft text-accent border-accent/30',
  warn: 'bg-warn/12 text-warn border-warn/30',
  danger: 'bg-danger/12 text-danger border-danger/30',
  info: 'bg-info/12 text-info border-info/30',
  muted: 'bg-transparent text-text-dim border-border',
};

export function Badge({
  children,
  tone = 'neutral',
  className,
  title,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] leading-5',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-[var(--radius)] border border-dashed border-border px-6 py-10 text-center',
        className,
      )}
    >
      {icon ? <div className="text-text-dim">{icon}</div> : null}
      <p className="text-sm font-medium text-text">{title}</p>
      {description ? <p className="max-w-md text-xs text-text-muted">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn('animate-pulse rounded-[var(--radius-sm)] bg-surface-2', className)}
    />
  );
}

export function ProgressBar({
  value,
  max = 100,
  label,
  tone = 'accent',
  className,
}: {
  value: number;
  max?: number;
  label?: string;
  tone?: 'accent' | 'warn' | 'info';
  className?: string;
}) {
  const percent = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  const fill = tone === 'warn' ? 'bg-warn' : tone === 'info' ? 'bg-info' : 'bg-accent';
  return (
    <div className={cn('space-y-1', className)}>
      {label ? (
        <div className="flex justify-between text-[11px] text-text-dim">
          <span>{label}</span>
          <span>{Math.round(percent)}%</span>
        </div>
      ) : null}
      <div
        role="progressbar"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? '进度'}
        className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
      >
        <div className={cn('h-full rounded-full transition-[width] duration-300', fill)} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
