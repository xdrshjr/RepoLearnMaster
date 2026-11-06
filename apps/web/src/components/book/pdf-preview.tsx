'use client';

import Link from 'next/link';
import { FileText, Printer, RefreshCcw } from 'lucide-react';
import { useEffect } from 'react';

import { Badge, Card, CardHeader, EmptyState, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/toast';
import { SiteHeader } from '@/components/shell/site-header';
import { isApiError } from '@/lib/api/client';
import { useBook, useCreatePdf, usePdfStatus } from '@/lib/api/hooks';
import { formatBytes, formatDateTime } from '@/lib/format';

/**
 * P10 PDF — spec §7.2 / §5.2.
 *
 * When the engine is `browser-print` we must NOT offer a fake PDF download: the
 * backend never produced bytes. The page then points at the print view instead.
 */
export function PdfPreview({ bookId }: { bookId: string }) {
  const toast = useToast();
  const book = useBook(bookId);
  const pdf = usePdfStatus(bookId, true);
  const createPdf = useCreatePdf(bookId);

  const status = pdf.data?.status ?? 'queued';
  const isPrintEngine = pdf.data?.engine === 'browser-print';
  const pending = status === 'queued' || status === 'running' || status === 'generating';

  const refetchPdf = pdf.refetch;
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => {
      void refetchPdf();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [pending, refetchPdf]);

  const generate = () => {
    createPdf.mutate(
      { engine: 'chromium' },
      {
        onSuccess: () => {
          toast.push({ tone: 'info', title: '已开始生成 PDF', description: '页数与体积会在完成后显示。' });
          void pdf.refetch();
        },
        onError: (error) => {
          const apiError = isApiError(error) ? error : null;
          toast.push({
            tone: 'error',
            title: apiError ? `${apiError.title} · ${apiError.code}` : '生成 PDF 失败',
            description: apiError?.hint ?? error.message,
          });
        },
      },
    );
  };

  return (
    <>
      <SiteHeader
        context={`${book.data?.title ?? '课程书籍'} · 导出`}
        right={
          <Link
            href={`/book/${encodeURIComponent(bookId)}`}
            className="rounded-[var(--radius-sm)] px-2.5 py-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
          >
            回阅读
          </Link>
        }
      />
      <main id="main" className="mx-auto w-full max-w-[760px] space-y-3 px-4 py-6">
        <div className="flex items-center gap-2">
          <FileText className="size-4 text-accent" aria-hidden />
          <h1 className="text-base font-semibold text-text">PDF 预览与下载</h1>
          <Badge tone={isPrintEngine ? 'warn' : pending ? 'info' : status === 'ready' ? 'accent' : 'muted'}>
            {isPrintEngine ? 'browser-print' : status}
          </Badge>
        </div>

        {pdf.isLoading ? (
          <Skeleton className="h-40" />
        ) : pdf.isError ? (
          <EmptyState
            title="拿不到 PDF 状态"
            description={pdf.error instanceof Error ? pdf.error.message : '稍后重试。'}
            action={
              <Button variant="outline" size="sm" onClick={() => void pdf.refetch()}>
                重试
              </Button>
            }
          />
        ) : isPrintEngine ? (
          <Card className="space-y-3 border-warn/40 bg-warn/5">
            <CardHeader
              title="本次使用浏览器打印引擎"
              subtitle="后端没有生成 PDF 文件（engine=browser-print），因此这里不提供“假下载”。"
            />
            <p className="text-[11px] leading-[1.65] text-text-muted">
              可以直接打开打印视图，用浏览器自带的“打印 / 另存为 PDF”。字号、页码与章节书签由打印样式表控制，
              内容与在线书籍完全一致。
            </p>
            <div className="flex flex-wrap gap-2">
              <a
                href={pdf.data?.print_view_url ?? `/book/${encodeURIComponent(bookId)}?print=1`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-sm)] bg-accent px-3 text-xs font-semibold text-[#06110c] hover:bg-accent-strong"
              >
                <Printer className="size-3.5" aria-hidden />
                打开打印视图
              </a>
              <Button variant="outline" size="sm" onClick={generate} loading={createPdf.isPending}>
                改用 Chromium 生成 PDF
              </Button>
            </div>
          </Card>
        ) : pdf.data?.pdf_url ? (
          <Card className="space-y-3">
            <CardHeader title="PDF 已生成" subtitle="下载地址同源代理，支持 Range 分段加载。" />
            <dl className="grid grid-cols-2 gap-2 text-[11px]">
              <div>
                <dt className="text-text-dim">页数</dt>
                <dd className="text-text">{pdf.data.pages || '—'}</dd>
              </div>
              <div>
                <dt className="text-text-dim">体积</dt>
                <dd className="text-text">{formatBytes(pdf.data.bytes)}</dd>
              </div>
              <div>
                <dt className="text-text-dim">生成时间</dt>
                <dd className="text-text">{formatDateTime(pdf.data.generated_at)}</dd>
              </div>
              <div>
                <dt className="text-text-dim">源码 commit</dt>
                <dd className="font-mono text-text">{pdf.data.commit_sha?.slice(0, 10) || '—'}</dd>
              </div>
            </dl>
            <div className="flex flex-wrap gap-2">
              <a
                href={pdf.data.pdf_url}
                className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-sm)] bg-accent px-3 text-xs font-semibold text-[#06110c] hover:bg-accent-strong"
                download
              >
                下载 PDF
              </a>
              <a
                href={pdf.data.pdf_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-9 items-center rounded-[var(--radius-sm)] border border-border px-3 text-xs text-text hover:border-accent/50"
              >
                在新标签打开
              </a>
              <Button variant="ghost" size="sm" onClick={() => void pdf.refetch()} icon={<RefreshCcw className="size-3" aria-hidden />}>
                刷新状态
              </Button>
            </div>
            <iframe
              title="PDF 预览"
              src={pdf.data.pdf_url}
              className="h-[60vh] w-full rounded-[var(--radius-sm)] border border-border bg-code-bg"
            />
          </Card>
        ) : (
          <Card className="space-y-3">
            <CardHeader
              title={pending ? '正在生成 PDF…' : '还没有 PDF'}
              subtitle={pending ? 'Chromium 渲染中；大书通常需要 20–60 秒。' : '生成后会显示页数、体积与源码 commit。'}
            />
            {pdf.data?.error && Object.keys(pdf.data.error).length > 0 ? (
              <p className="rounded-[var(--radius-sm)] border border-danger/40 bg-danger/10 px-2 py-1.5 text-[11px] text-danger">
                {String((pdf.data.error as { message?: string }).message ?? 'PDF 生成失败')}
              </p>
            ) : null}
            <div className="flex gap-2">
              <Button variant="primary" size="sm" onClick={generate} loading={createPdf.isPending} disabled={pending}>
                {pending ? '生成中…' : '生成 PDF'}
              </Button>
              <Button variant="outline" size="sm" onClick={() => void pdf.refetch()} icon={<RefreshCcw className="size-3" aria-hidden />}>
                刷新
              </Button>
            </div>
            <p className="text-[10px] leading-[1.6] text-text-dim">
              提示：Chromium 不可用的环境会自动退化为 browser-print 引擎，此时本页会改为“打开打印视图”。
            </p>
          </Card>
        )}
      </main>
    </>
  );
}
