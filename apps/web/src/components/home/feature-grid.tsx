import { BookOpen, Boxes, MessagesSquare, RefreshCcw } from 'lucide-react';

const FEATURES = [
  {
    icon: Boxes,
    title: '分层学习',
    description:
      '先看宏观架构，再跟着全局走读过一遍调用链，最后深入源码逐行读。三层各有自己的课时与测验。',
    accent: '宏观 → 走读 → 深入',
  },
  {
    icon: BookOpen,
    title: '交互式走读',
    description:
      '讲解与代码联动：字幕推进时代码自动跳到对应行，架构节点可点、变量面板标注示例值，随时看调用链。',
    accent: '字幕 · 高亮 · 板书同步',
  },
  {
    icon: MessagesSquare,
    title: '随时提问',
    description:
      '选中任意几行代码就能问“这行为什么这样写”。答案带证据列表，点一下跳回 file:line，不给你猜。',
    accent: '证据可追溯',
  },
  {
    icon: RefreshCcw,
    title: '课程可复用',
    description:
      '同一 commit 命中缓存直接复用，仓库更新后旧课程仍可学；课程还能导出成在线书籍与 PDF。',
    accent: '缓存 · 版本化 · 可导出',
  },
];

export function FeatureGrid() {
  return (
    <section aria-labelledby="features-title" className="mx-auto mt-16 w-full max-w-[1040px] px-4">
      <h2 id="features-title" className="sr-only">
        产品能力
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {FEATURES.map((feature) => {
          const Icon = feature.icon;
          return (
            <article
              key={feature.title}
              className="rounded-[var(--radius)] border border-border bg-surface p-4 transition-colors hover:border-border-strong"
            >
              <div className="mb-2 flex items-center gap-2">
                <span className="grid size-8 place-items-center rounded-[var(--radius-sm)] bg-accent-soft text-accent">
                  <Icon className="size-4" aria-hidden />
                </span>
                <h3 className="text-sm font-semibold text-text">{feature.title}</h3>
              </div>
              <p className="text-xs leading-[1.65] text-text-muted">{feature.description}</p>
              <p className="mt-3 text-[11px] text-accent">{feature.accent}</p>
            </article>
          );
        })}
      </div>
    </section>
  );
}
