import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-dvh max-w-[520px] flex-col items-center justify-center gap-3 px-4 text-center">
      <p className="font-mono text-[11px] text-text-dim">404</p>
      <h1 className="text-base font-semibold text-text">这个页面不存在</h1>
      <p className="text-xs leading-[1.65] text-text-muted">
        课程 / 书籍的链接可能已经过期，或者这个仓库还没有生成过课程。
      </p>
      <div className="flex gap-2">
        <Link
          href="/"
          className="inline-flex h-10 items-center rounded-[var(--radius-sm)] bg-accent px-4 text-sm font-semibold text-[#06110c] hover:bg-accent-strong"
        >
          回首页粘贴仓库地址
        </Link>
        <Link
          href="/settings"
          className="inline-flex h-10 items-center rounded-[var(--radius-sm)] border border-border px-4 text-sm text-text hover:border-accent/50"
        >
          打开设置
        </Link>
      </div>
    </div>
  );
}
