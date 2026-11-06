'use client';

import { RefreshCcw, ServerCrash, Terminal } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

/**
 * Backend-not-ready view — spec §3.6.1 rule 3.
 *
 * When `/api/setup/state` fails we neither let the user through (that would
 * pretend setup succeeded) nor bounce them (that is a redirect loop). We show
 * the exact steps that fix it, plus a retry button.
 */
export function KernelNotReady({
  message,
  hint,
  onRetry,
  retrying,
}: {
  message: string;
  hint?: string;
  onRetry: () => void;
  retrying: boolean;
}) {
  return (
    <Card className="border-warn/40 bg-warn/5" role="alert">
      <div className="flex items-start gap-3">
        <ServerCrash className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-text">后端未就绪</h2>
          <p className="mt-1 text-xs text-text-muted">{message}</p>
          {hint ? <p className="mt-1 text-[11px] text-text-dim">{hint}</p> : null}

          <ol className="mt-3 space-y-1.5 text-[11px] leading-[1.65] text-text-muted">
            <li>
              1. 在仓库根目录运行{' '}
              <code className="rounded bg-code-bg px-1.5 py-0.5 font-mono text-[11px] text-accent">
                .\start.ps1
              </code>{' '}
              启动三进程（web :3000 / api :8000 / kernel :8787）。
            </li>
            <li>
              2. 确认 API 存活：
              <a
                className="ml-1 inline-flex items-center gap-1 text-accent underline underline-offset-2"
                href="/api/healthz"
                target="_blank"
                rel="noreferrer"
              >
                <Terminal className="size-3" aria-hidden />
                /api/healthz
              </a>{' '}
              应返回 <code className="font-mono">{"{ok:true}"}</code>。
            </li>
            <li>
              3. 日志在 <code className="font-mono">var/logs/api.log</code>、{' '}
              <code className="font-mono">var/logs/web.log</code>；端口占用与迁移失败都会打在这里。
            </li>
            <li>
              4. 想先看界面：可以访问设置页的诊断面板查看 G1/G2/G3 Gate 的实际状态。
            </li>
          </ol>

          <div className="mt-3 flex items-center gap-2">
            <Button variant="primary" size="sm" onClick={onRetry} loading={retrying} icon={<RefreshCcw className="size-3.5" aria-hidden />}>
              重试连接
            </Button>
            <a
              href="/settings#doctor"
              className="text-[11px] text-accent underline underline-offset-2"
            >
              打开诊断面板
            </a>
          </div>
        </div>
      </div>
    </Card>
  );
}
