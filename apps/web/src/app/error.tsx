'use client';

import { useEffect } from 'react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Logo } from '@/components/shell/site-header';

/**
 * Route-level error boundary. A failed fetch must never leave a blank screen:
 * the message + a retry + a way home are always available (§7.6 empty/error
 * states).
 */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[repolearn] route error', error);
  }, [error]);

  return (
    <div className="mx-auto flex min-h-dvh max-w-[560px] flex-col items-center justify-center gap-3 px-4 text-center">
      <Logo />
      <h1 className="mt-2 text-base font-semibold text-text">这个页面出错了</h1>
      <p className="text-xs leading-[1.65] text-text-muted">
        {error.message || '未知错误。'}
        {error.digest ? (
          <span className="mt-1 block font-mono text-[10px] text-text-dim">digest {error.digest}</span>
        ) : null}
      </p>
      <div className="mt-2 flex gap-2">
        <Button variant="primary" onClick={reset}>
          重试
        </Button>
        <Link
          href="/"
          className="inline-flex h-10 items-center rounded-[var(--radius-sm)] border border-border px-4 text-sm text-text hover:border-accent/50"
        >
          回首页
        </Link>
      </div>
      <p className="mt-1 text-[10px] text-text-dim">
        如果持续失败：确认后端已启动（<code className="font-mono">.\start.ps1</code>），或到设置 → 诊断面板查看 Gate 状态。
      </p>
    </div>
  );
}
