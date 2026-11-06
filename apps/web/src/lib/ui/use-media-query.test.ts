import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToString } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useIsWide, useMediaQuery, WIDE_MEDIA_QUERY } from '@/lib/ui/use-media-query';

type ChangeListener = (event: MediaQueryListEvent) => void;

/**
 * 本机（以及 CI）跑 vitest 时 `NODE_ENV=production`，React 用的是生产构建，
 * 里面的 `React.act` 不存在，于是 `@testing-library/react` 的 `render/renderHook`
 * 在构造上报 "React.act is not a function"。这里直接用手写 `createRoot` +
 * `vi.waitFor`，既不依赖 act，也不引入任何新依赖。
 */
function mountProbe() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  function Probe() {
    // 这个文件保持 `.ts`（spec §4.6 文件 25），所以用 createElement 而不是 JSX
    return createElement('span', null, String(useIsWide()));
  }

  root.render(createElement(Probe));
  return {
    container,
    unmount: () => {
      root.unmount();
      container.remove();
    },
  };
}

/**
 * 手写 `matchMedia` 假件（jsdom 自带的那份 matches 恒为 false，无法模拟"变宽"）。
 * 只实现本 hook 用到的三件事：`matches`、`addEventListener('change')`、
 * `removeEventListener('change')`。
 */
function installMatchMedia(initialMatches: boolean) {
  const listeners = new Set<ChangeListener>();
  let matches = initialMatches;

  const addEventListener = vi.fn((type: string, listener: ChangeListener) => {
    if (type === 'change') listeners.add(listener);
  });
  const removeEventListener = vi.fn((type: string, listener: ChangeListener) => {
    if (type === 'change') listeners.delete(listener);
  });

  const mediaQueryList = {
    get matches() {
      return matches;
    },
    media: WIDE_MEDIA_QUERY,
    onchange: null,
    addEventListener,
    removeEventListener,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList;

  const matchMedia = vi.fn((_query: string) => mediaQueryList);
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: matchMedia,
  });

  return {
    matchMedia,
    addEventListener,
    removeEventListener,
    listenerCount: () => listeners.size,
    setMatches(next: boolean) {
      matches = next;
      for (const listener of [...listeners]) {
        listener({ matches: next, media: WIDE_MEDIA_QUERY } as MediaQueryListEvent);
      }
    },
  };
}

afterEach(() => {
  // jsdom 把 matchMedia 挂在 window 原型上，删掉自有属性即可复原
  Reflect.deleteProperty(window, 'matchMedia');
});

describe('useMediaQuery', () => {
  it('服务端快照恒为 false：即使 matchMedia 现在就匹配，SSR 也先渲染窄屏布局', async () => {
    installMatchMedia(true);

    function Probe() {
      return createElement('span', null, String(useIsWide()));
    }

    // 服务端渲染只走 getServerSnapshot，因此必然是 "false"（首帧不变形）
    expect(renderToString(createElement(Probe))).toBe('<span>false</span>');

    // 同一环境下客户端渲染读到真实值，说明"首帧 false"不是硬编码
    const probe = mountProbe();
    await vi.waitFor(() => expect(probe.container.textContent).toBe('true'));
    probe.unmount();
  });

  it('订阅 change，并在解绑时移除同一个监听器', async () => {
    const fake = installMatchMedia(false);
    const probe = mountProbe();
    await vi.waitFor(() => expect(probe.container.textContent).toBe('false'));

    expect(fake.addEventListener).toHaveBeenCalledTimes(1);
    expect(fake.addEventListener.mock.calls[0]?.[0]).toBe('change');
    expect(fake.listenerCount()).toBe(1);

    probe.unmount();

    expect(fake.removeEventListener).toHaveBeenCalledTimes(1);
    expect(fake.removeEventListener.mock.calls[0]?.[0]).toBe('change');
    // 同一个函数引用，否则解绑等于没做
    expect(fake.removeEventListener.mock.calls[0]?.[1]).toBe(fake.addEventListener.mock.calls[0]?.[1]);
    expect(fake.listenerCount()).toBe(0);
  });

  it('matchMedia 触发 change 后重渲染（false → true → false）', async () => {
    const fake = installMatchMedia(false);
    const probe = mountProbe();
    await vi.waitFor(() => expect(probe.container.textContent).toBe('false'));

    fake.setMatches(true);
    await vi.waitFor(() => expect(probe.container.textContent).toBe('true'));

    fake.setMatches(false);
    await vi.waitFor(() => expect(probe.container.textContent).toBe('false'));

    probe.unmount();
  });
});
