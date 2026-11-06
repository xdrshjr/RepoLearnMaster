import type { Metadata, Viewport } from 'next';

import './globals.css';
import { QueryProvider } from '@/components/providers/query-provider';
import { ToastProvider } from '@/components/ui/toast';

export const metadata: Metadata = {
  title: {
    default: 'RepoLearn · 把任何 GitHub 仓库变成一节可走读的课',
    template: '%s · RepoLearn',
  },
  description:
    'RepoLearn 粘贴一个 GitHub 仓库地址，就生成三层 AI 课程：宏观架构 → 全局走读 → 深入源码，每一句讲解都能落回 file:line。',
  applicationName: 'RepoLearn',
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: '#0B0F0E',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-dvh bg-bg font-sans text-text antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-[var(--radius-sm)] focus:bg-surface focus:px-3 focus:py-2 focus:text-sm"
        >
          跳到主要内容
        </a>
        <ToastProvider>
          <QueryProvider>{children}</QueryProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
