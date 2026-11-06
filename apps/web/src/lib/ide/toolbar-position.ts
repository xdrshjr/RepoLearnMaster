/**
 * 选区工具条定位（spec §3.3.2 · D29 / 评审 P1-6、P2-9）。
 *
 * 这里是**纯算术**：不含 DOM 调用，也不读 `window`。调用方（`SelectionToolbar`）
 * 负责在 `useLayoutEffect` 里量出工具条的真实尺寸与视口，再调本函数。
 * 之所以把这段从组件里抠出来，是因为"D29 工具条出屏"只有靠边界用例才能钉住
 * （T-A11Y-3），而组件内的测量逻辑没法在 jsdom 里做出真实布局。
 *
 * 坐标全部是**视口坐标**（与 `getBoundingClientRect()` 同一坐标系），
 * 因此组件侧用 `position: fixed` 渲染。
 */

export interface Rect {
  top: number;
  left: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface Viewport {
  width: number;
  height: number;
}

/** 工具条与视口四边之间必须保留的最小留白（px）。 */
export const TOOLBAR_MARGIN = 8;

/** 工具条与选区之间的距离（px）。 */
export const TOOLBAR_GAP = 6;

/**
 * 把工具条塞回视口内。
 *
 * 约定：`anchor.top` 是**选区基线**（选区 rect 的底边），`anchor.left` 是选区左边界。
 * 所以"放在选区下方"= `anchor.top + TOOLBAR_GAP`，而不是 `anchor.top`（后者会压住
 * 最后一行文字）。flip 到上方时以基线为下沿，属于"下方完全放不下"的退化形态：
 * 宁可略微压住选区，也要保证整条工具条可见——看不见的工具条等于没有工具条。
 */
export function clampToolbarPosition(anchor: Rect, size: Size, viewport: Viewport): Rect {
  // 1) 水平先 clamp 到 [MARGIN, width - size.width - MARGIN]。
  //    视口比工具条还窄（例如 320px 屏上尚未换行的长工具条）时 `maxLeft` 会小于
  //    MARGIN，此时退化为 MARGIN —— 绝不返回负数。负的 left 会把整条工具条推到
  //    视口左边界之外，症状与"右边被切掉"一样：按钮点不到。
  const maxLeft = viewport.width - size.width - TOOLBAR_MARGIN;
  const left = maxLeft <= TOOLBAR_MARGIN
    ? TOOLBAR_MARGIN
    : Math.min(Math.max(anchor.left, TOOLBAR_MARGIN), maxLeft);

  // 2) 垂直：优先下方；下方放不下就翻到上方；两处都放不下才做垂直 clamp。
  const below = anchor.top + TOOLBAR_GAP;
  const above = anchor.top - size.height - TOOLBAR_GAP;
  const bottomLimit = viewport.height - size.height - TOOLBAR_MARGIN;

  let top: number;
  if (below <= bottomLimit) {
    top = below;
  } else if (above >= TOOLBAR_MARGIN) {
    top = above;
  } else if (bottomLimit <= TOOLBAR_MARGIN) {
    // 视口本身就装不下工具条（极端窄高场景）：贴住上边距，剩下的交给
    // `max-w-[calc(100vw-16px)] flex-wrap` 让按钮换行，而不是让 top 变负。
    top = TOOLBAR_MARGIN;
  } else {
    top = Math.min(Math.max(below, TOOLBAR_MARGIN), bottomLimit);
  }

  return { top, left };
}
