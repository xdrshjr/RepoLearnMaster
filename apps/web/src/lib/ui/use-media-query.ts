'use client';

import { useCallback, useSyncExternalStore } from 'react';

/**
 * `matchMedia` 的 SSR 安全封装（spec §3.3.2 · D30 / §4.6 文件 24–25）。
 *
 * 用 `useSyncExternalStore` 而不是 `useState + useEffect`：
 *  · 首帧（服务端与 hydration 那一次）必须给出一个**确定**值，否则深链页会在
 *    宽屏上先渲染一套窄屏 DOM、hydrate 后再换成另一套，出现布局跳动；
 *  · 这里首帧固定返回 `false`（= 窄屏分支），因为窄屏分支是既有双栏布局的
 *    超集——先窄后宽只是"多一次重渲染"，先宽后窄会让用户在首屏看到被裁掉的
 *    代码区；
 *  · `useEffect + setState` 写法在服务端渲染时会拿到 `undefined`，
 *    然后靠"第二次渲染"修正，那正是要避免的两帧不一致。
 */

/** 深度源码页的双栏断点：`xl` = 1280px（沿用 Tailwind 默认值，不新造断点）。 */
export const WIDE_MEDIA_QUERY = '(min-width: 1280px)';

function getMediaQueryList(query: string): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null;
  return window.matchMedia(query);
}

function subscribe(query: string, onStoreChange: () => void): () => void {
  const mediaQueryList = getMediaQueryList(query);
  if (!mediaQueryList) return () => {};
  mediaQueryList.addEventListener('change', onStoreChange);
  // 必须在解绑时移除同一个引用，否则组件卸载后仍然持有闭包 → 内存泄漏，
  // 并且在 React 严格模式的双次挂载里会重复触发重渲染。
  return () => mediaQueryList.removeEventListener('change', onStoreChange);
}

/** 订阅任意媒体查询；服务端快照恒为 `false`。 */
export function useMediaQuery(query: string): boolean {
  const subscribeToQuery = useCallback((onStoreChange: () => void) => subscribe(query, onStoreChange), [query]);
  const getSnapshot = useCallback(() => getMediaQueryList(query)?.matches ?? false, [query]);
  const getServerSnapshot = useCallback(() => false, []);
  return useSyncExternalStore(subscribeToQuery, getSnapshot, getServerSnapshot);
}

/** 当前是否处于 `xl` 及以上（深度源码页用双栏布局的宽度）。 */
export function useIsWide(): boolean {
  return useMediaQuery(WIDE_MEDIA_QUERY);
}
