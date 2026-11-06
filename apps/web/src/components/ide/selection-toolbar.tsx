'use client';

import { MessageSquarePlus, Sparkles, Waypoints } from 'lucide-react';
import { useLayoutEffect, useRef, useState } from 'react';

import { ASK_ACTIONS, type AskActionId } from '@/lib/ide/decorations';
import {
  clampToolbarPosition,
  TOOLBAR_MARGIN,
  type Rect,
  type Size,
  type Viewport,
} from '@/lib/ide/toolbar-position';
import type { LineSelection } from '@/stores/ide';

const ICONS: Record<AskActionId, typeof Sparkles> = {
  explain: Sparkles,
  why: Waypoints,
  alternatives: MessageSquarePlus,
};

/** 选区锚点 + 来源标记（`selection` = 真实选区 rect；`fallback` = 兜底偏移）。 */
export type SelectionAnchor = Rect & { source?: 'selection' | 'fallback' };

/** 上层给不出锚点时的最后兜底：既不依赖选区，也不依赖面板。 */
const FALLBACK_ANCHOR: Rect = { top: 96, left: 320 };

/**
 * Floating selection toolbar — spec §7.2 行内提问 / §3.3.2 D29.
 *
 * Rendered in a portal-free fixed layer (the code pane has `overflow: auto`,
 * which would clip an absolutely positioned child).
 *
 * **D29 的成因写在这里，避免有人把修法退回去**：旧实现是
 * `const position = anchor ?? {top: 96, left: 320}` + `left: Math.max(8, position.left)`，
 * 也就是"只挡负数、不挡溢出"，并且尺寸假定为常量。工具条实际宽 260–340px，
 * 在 390px 视口下 `left` 一旦大于 40 就整条出屏，三个动作按钮都点不到。
 * 现在分两步：① 渲染后（`useLayoutEffect`，在浏览器绘制前）量真实尺寸与视口；
 * ② 交给 `clampToolbarPosition` 做"水平 clamp + 下方优先/上方翻转"。
 * 尺寸只有渲染后才知道，所以测量不能挪到 `useMemo` 或渲染期里。
 *
 * 注意：`useLayoutEffect` 在服务端不执行，且本组件只在**用户选中之后**才渲染，
 * 因此不会产生 SSR 警告。
 */
export function SelectionToolbar({
  selection,
  anchor,
  onAsk,
  onDismiss,
  busy,
}: {
  selection: LineSelection;
  anchor: SelectionAnchor | null;
  onAsk: (actionId: AskActionId) => void;
  onDismiss: () => void;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState<Size | null>(null);
  const [viewport, setViewport] = useState<Viewport | null>(null);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;

    const measure = () => {
      const box = element.getBoundingClientRect();
      // 引用相等即不重渲染：否则每次测量都会触发一次新的布局效应
      setSize((previous) =>
        previous && previous.width === box.width && previous.height === box.height
          ? previous
          : { width: box.width, height: box.height },
      );
      setViewport((previous) =>
        previous && previous.width === window.innerWidth && previous.height === window.innerHeight
          ? previous
          : { width: window.innerWidth, height: window.innerHeight },
      );
    };

    measure();
    // 旋转屏幕 / 拖窄窗口后必须重新 clamp，否则会出现"刚还在视口里，一转身又跑出去了"
    window.addEventListener('resize', measure);
    window.addEventListener('orientationchange', measure);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('orientationchange', measure);
    };
  }, [selection.lineStart, selection.lineEnd, selection.text, busy]);

  const anchorPoint: Rect = anchor ?? FALLBACK_ANCHOR;
  // 第一帧（还没量到尺寸/视口）只保证不回负数；`useLayoutEffect` 会在**绘制前**
  // 用下面的 clamp 结果再渲染一次，用户看不到这个中间态。
  const position: Rect =
    size && viewport
      ? clampToolbarPosition(anchorPoint, size, viewport)
      : {
          top: Math.max(TOOLBAR_MARGIN, anchorPoint.top),
          left: Math.max(TOOLBAR_MARGIN, anchorPoint.left),
        };

  return (
    <div
      ref={ref}
      role="toolbar"
      aria-label="对选中的代码提问"
      // 端点断言用的确定性信号（T-TOUCH-1）：
      //  · data-anchor-source  锚点是否真的来自选区（这就是 D29 的分界线）
      //  · data-anchor-top/left 选区基线坐标（视口坐标，= 选区 rect 底边 / 左边界）
      //  · data-toolbar-top/left 最终落点（clamp 之后）
      data-rl-toolbar="selection"
      data-anchor-source={anchor?.source ?? 'fallback'}
      data-anchor-top={Math.round(anchorPoint.top)}
      data-anchor-left={Math.round(anchorPoint.left)}
      data-toolbar-top={Math.round(position.top)}
      data-toolbar-left={Math.round(position.left)}
      className="fixed z-40 flex max-w-[calc(100vw-16px)] flex-wrap items-center gap-1 rounded-[var(--radius)] border border-border-strong bg-surface p-1 shadow-[var(--shadow-soft)]"
      style={{ top: position.top, left: position.left }}
    >
      <span className="px-2 text-[11px] text-text-dim">
        {selection.lineStart === selection.lineEnd
          ? `第 ${selection.lineStart} 行`
          : `${selection.lineStart}–${selection.lineEnd} 行`}
      </span>
      {ASK_ACTIONS.map((action) => {
        const Icon = ICONS[action.id];
        return (
          <button
            key={action.id}
            type="button"
            disabled={busy}
            onClick={() => onAsk(action.id)}
            // 触屏视口（<lg）命中区 ≥44×44（spec §3.3.1 命中区契约）；≥lg 不受影响，桌面密度不变。
            // 必须写 px：本项目 `html` 的 font-size 是 14px，`h-11`（2.75rem）实际只有
            // 38.5px，T-TOUCH-4 的 43.5 下限会红——这类"看起来是 44、量出来是 38.5"
            // 的坑只有真跑一遍量 boundingBox 才会暴露。
            data-rl-tap=""
            className="inline-flex max-lg:min-h-[44px] items-center justify-center gap-1 rounded-[var(--radius-sm)] px-2 py-1.5 text-[11px] text-text-muted transition-colors hover:bg-accent-soft hover:text-accent disabled:opacity-50"
          >
            <Icon className="size-3" aria-hidden />
            {action.label}
          </button>
        );
      })}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="收起工具条"
        // 视觉上可以只有 16px（装饰性图标按钮），但**命中区**必须够：用 `::after`
        // 把可点区域向外扩 12px，视觉密度不变、触屏仍能命中（spec §3.3.1）。
        data-rl-tap=""
        className="relative rounded-[var(--radius-sm)] px-1.5 py-1 text-[11px] text-text-dim after:absolute after:-inset-3 after:content-[''] hover:text-text"
      >
        ✕
      </button>
    </div>
  );
}
