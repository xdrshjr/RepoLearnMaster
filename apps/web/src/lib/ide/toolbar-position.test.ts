import { describe, expect, it } from 'vitest';

import {
  clampToolbarPosition,
  TOOLBAR_GAP,
  TOOLBAR_MARGIN,
  type Rect,
  type Size,
  type Viewport,
} from '@/lib/ide/toolbar-position';

const IPHONE_12: Viewport = { width: 390, height: 844 };
const NARROW: Viewport = { width: 320, height: 568 };
const DESKTOP: Viewport = { width: 1440, height: 900 };
/** 三个动作按钮 + 行号标签 + ✕，实测宽度大约在 260–340 之间（spec §3.3.2）。 */
const TOOLBAR: Size = { width: 260, height: 36 };

/** 断言工具条四边都在视口内（D29 的"用户点得到"的最低条件）。 */
function expectInsideViewport(position: Rect, size: Size, viewport: Viewport) {
  expect(position.left).toBeGreaterThanOrEqual(0);
  expect(position.top).toBeGreaterThanOrEqual(0);
  expect(position.left + size.width).toBeLessThanOrEqual(viewport.width);
  expect(position.top + size.height).toBeLessThanOrEqual(viewport.height);
}

describe('clampToolbarPosition', () => {
  it('390×844：下方放得下时贴着选区底边 + TOOLBAR_GAP，且横向跟随选区左边界', () => {
    const anchor: Rect = { top: 300, left: 40 };
    const position = clampToolbarPosition(anchor, TOOLBAR, IPHONE_12);
    expect(position.top).toBe(anchor.top + TOOLBAR_GAP);
    expect(position.left).toBe(anchor.left);
    expectInsideViewport(position, TOOLBAR, IPHONE_12);
  });

  it('390×844 选区贴右：right 被切掉的情况被改写成 left = width - 工具条宽 - MARGIN', () => {
    const anchor: Rect = { top: 300, left: 330 };
    const position = clampToolbarPosition(anchor, TOOLBAR, IPHONE_12);
    expect(position.left).toBe(IPHONE_12.width - TOOLBAR.width - TOOLBAR_MARGIN);
    expectInsideViewport(position, TOOLBAR, IPHONE_12);
  });

  it('320×568：选区靠右时仍然整条可见（这是 390 视口之外的第二道窄屏闸门）', () => {
    const size: Size = { width: 300, height: 36 };
    const anchor: Rect = { top: 200, left: 200 };
    const position = clampToolbarPosition(anchor, size, NARROW);
    // 320 - 300 - 8 = 12：clamp 后仍应 ≥ MARGIN
    expect(position.left).toBe(12);
    expect(position.left).toBeGreaterThanOrEqual(TOOLBAR_MARGIN);
    expectInsideViewport(position, size, NARROW);
  });

  it('工具条比视口还宽（size.width > viewport.width）：退化为 MARGIN，绝不返回负数', () => {
    const size: Size = { width: 400, height: 36 };
    const anchor: Rect = { top: 200, left: 120 };
    const position = clampToolbarPosition(anchor, size, IPHONE_12);
    expect(position.left).toBe(TOOLBAR_MARGIN);
    expect(position.left).toBeGreaterThanOrEqual(0);
  });

  it('anchor.left 为负（选区起点在视口左侧之外）：left 回正到 MARGIN', () => {
    const anchor: Rect = { top: 120, left: -48 };
    const position = clampToolbarPosition(anchor, TOOLBAR, NARROW);
    expect(position.left).toBe(TOOLBAR_MARGIN);
    expect(position.top).toBe(anchor.top + TOOLBAR_GAP);
  });

  it('选区贴底（390×844）：翻到选区上方，而不是被视口底边切掉', () => {
    const anchor: Rect = { top: 830, left: 40 };
    const position = clampToolbarPosition(anchor, TOOLBAR, IPHONE_12);
    // 下方会越界（836 + 36 > 844 - 8），翻上去
    expect(position.top).toBe(anchor.top - TOOLBAR.height - TOOLBAR_GAP);
    expectInsideViewport(position, TOOLBAR, IPHONE_12);
  });

  it('上下都放不下的极端视口：走垂直 clamp，top 依然是正数且整条可见', () => {
    const viewport: Viewport = { width: 320, height: 90 };
    const size: Size = { width: 300, height: 44 };
    const anchor: Rect = { top: 40, left: 10 };
    const position = clampToolbarPosition(anchor, size, viewport);
    expect(position.top).toBeGreaterThanOrEqual(TOOLBAR_MARGIN);
    // 下方越界、上方也越界 → clamp 到 height - 工具条高 - MARGIN
    expect(position.top).toBe(viewport.height - size.height - TOOLBAR_MARGIN);
    expectInsideViewport(position, size, viewport);
  });

  it('桌面 1440×900：空间充足时不做任何改写（工具条精确跟着选区走）', () => {
    const anchor: Rect = { top: 412, left: 512 };
    const position = clampToolbarPosition(anchor, TOOLBAR, DESKTOP);
    expect(position).toEqual({ top: anchor.top + TOOLBAR_GAP, left: anchor.left });
  });
});
