'use client';

import { useEffect, useRef, type ReactNode } from 'react';

import { Tabs } from '@/components/ui/overlay';
import { cn } from '@/lib/utils';

/**
 * `<xl` 的三段切换（spec §3.3.2 · D30 / §4.6 文件 22）。
 *
 * 窄屏上深度源码页退化成"代码 → 执行 → 提问"三段，而不是把三块纵向堆在
 * 一列里——旧布局首屏被 `min-h-[480px]` 的代码区占满，用户看完代码既看不到
 * 工具条也不知道可以问。
 *
 * 关键约束（否则会直接打红既有 `learning.spec.ts`）：**`≥xl` 时这个组件根本
 * 不渲染**，双栏布局由页面自己给。多渲染一份 `role="tab"` 会让 `getByRole('tab')`
 * 命中歧义。
 */

export type WorkspacePane = 'code' | 'execution' | 'ask';

const PANES: Array<{ value: WorkspacePane; label: string }> = [
  { value: 'code', label: '代码' },
  { value: 'execution', label: '执行' },
  { value: 'ask', label: '提问' },
];

export interface PaneSwitcherProps {
  value: WorkspacePane;
  onChange: (pane: WorkspacePane) => void;
  code: ReactNode;
  execution: ReactNode;
  ask: ReactNode;
  className?: string;
}

export function PaneSwitcher({ value, onChange, code, execution, ask, className }: PaneSwitcherProps) {
  const tabsRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);

  // `Tabs` 是共享组件（本轮不在改动清单里），没有留 `data-rl-tap` 的口子。
  // 命中区门禁只认显式登记的元素（spec §3.3.1），所以在这里把自己的三个 tab
  // 登记进去；尺寸由容器上的 arbitrary variant 撑到 ≥44（`lg` 以下）。
  useEffect(() => {
    const buttons = tabsRef.current?.querySelectorAll<HTMLElement>('[role="tab"]');
    buttons?.forEach((button) => button.setAttribute('data-rl-tap', ''));
  }, []);

  // 切到「提问」就把焦点送进输入框：窄屏下"点了提问还得自己找输入框"是这条
  // 链路最容易掉的一环，T-TOUCH-3 断言的正是 focus 落在 textarea 上。
  useEffect(() => {
    if (value !== 'ask') return;
    const textarea = contentRef.current?.querySelector('textarea');
    textarea?.focus();
  }, [value]);

  return (
    <div data-pane-switcher="" className={cn('flex min-h-0 flex-col', className)}>
      {/* 固定在工作区顶部：滚动浏览代码时随时能切回「提问」。
          命中区写死 `[44px]` 而不是 `h-11`——本项目 html 的 font-size 是 14px，
          `h-11`（2.75rem）只有 38.5px，T-TOUCH-4 会红。 */}
      <div ref={tabsRef} className="sticky top-0 z-20 bg-bg pt-1">
        <Tabs
          tabs={PANES}
          value={value}
          onChange={onChange}
          ariaLabel="深度源码视图"
          className="bg-bg [&_[role=tab]]:min-h-[44px] [&_[role=tab]]:flex-1 [&_[role=tab]]:text-center"
        />
      </div>
      <div ref={contentRef} data-pane={value} className="min-h-0 flex-1 pt-3">
        {/*
          三段**全部挂载**、只切可见性。卸载会带来两个回归：
          ① `CodePane` 的锚点是局部 state，选区却在 zustand（跨卸载存活），
             切回「代码」时选区还在、锚点为 null → 工具条退回"面板左上角 +
             固定偏移"，也就是 D29 修掉的那个老毛病；
          ② Monaco 实例每次切回都要重挂，用户看到 4.5s 骨架屏后才恢复。
          `hidden` 的子树不进无障碍树，role 查询也不会命中，门禁不受影响。
        */}
        <div data-pane-panel="code" className={value === 'code' ? '' : 'hidden'}>
          {code}
        </div>
        <div data-pane-panel="execution" className={value === 'execution' ? '' : 'hidden'}>
          {execution}
        </div>
        <div data-pane-panel="ask" className={value === 'ask' ? '' : 'hidden'}>
          {ask}
        </div>
      </div>
    </div>
  );
}
