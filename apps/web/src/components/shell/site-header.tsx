import Link from 'next/link';

import { cn } from '@/lib/utils';

export interface SiteHeaderProps {
  /** Breadcrumb-ish context shown next to the logo (e.g. course title). */
  context?: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
  sticky?: boolean;
}

export function Logo() {
  return (
    <span className="flex items-center gap-2 text-sm font-semibold tracking-tight text-text">
      <span aria-hidden className="grid size-6 place-items-center rounded-[7px] bg-accent text-[11px] font-bold text-[#06110c]">
        R
      </span>
      RepoLearn
      <span aria-hidden className="size-1.5 rounded-full bg-accent" />
    </span>
  );
}

export function SiteHeader({ context, right, className, sticky = true }: SiteHeaderProps) {
  return (
    <header
      className={cn(
        'z-30 flex h-12 items-center gap-4 border-b border-border bg-bg/90 px-4 backdrop-blur',
        sticky && 'sticky top-0',
        className,
      )}
    >
      <Link href="/" className="flex items-center">
        <Logo />
      </Link>
      <div className="min-w-0 flex-1 truncate text-xs text-text-dim">{context}</div>
      <nav className="flex items-center gap-1 text-xs">
        {right}
        <Link
          href="/settings"
          className="rounded-[var(--radius-sm)] px-2.5 py-1.5 text-text-muted transition-colors hover:bg-surface-2 hover:text-text"
        >
          设置
        </Link>
        <Link
          href="/setup"
          className="rounded-[var(--radius-sm)] px-2.5 py-1.5 text-text-muted transition-colors hover:bg-surface-2 hover:text-text"
        >
          配置向导
        </Link>
      </nav>
    </header>
  );
}
