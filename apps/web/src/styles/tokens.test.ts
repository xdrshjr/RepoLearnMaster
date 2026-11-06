/**
 * @vitest-environment node
 *
 * 这个测试只读文件、不渲染 DOM，因此在 node 环境里跑：默认的 jsdom 环境会把
 * `node:fs` / `node:url` 当成浏览器不可用模块 externalize 掉，断言就永远起不来。
 */

/**
 * T-RM-1 — 动效门禁（spec §3.3.3 / §7.7 A4）。
 *
 * 这里是**静态**断言，不是 Playwright 的计算样式断言：`0.01ms` 的取整在不同引擎
 * 上不一致，改成运行时断言会变成噪声门禁，然后被人删掉（§10 不采纳第 5 条）。
 *
 * 同一份文件里还锁住三件"改了就再也回不来"的样式约定：
 *  · `--tap-target: 44px` —— 触屏命中区的唯一真源（§3.3.1）；
 *  · 安全区 `env(safe-area-inset-*)` —— 刘海屏底部工具条被手势条压住；
 *  · 全局 `min-height: 32px` 必须留在 `@layer base` 里 —— 它一旦回到无层级位置，
 *    就会压过 Tailwind 的 `@layer utilities`，组件上的 `min-h-11` 会静默失效，
 *    而这种失败只有真机上才看得见。
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const CSS_PATH = fileURLToPath(new URL('./tokens.css', import.meta.url));
const css = readFileSync(CSS_PATH, 'utf8');

function block(source: string, opener: RegExp): string | null {
  const match = opener.exec(source);
  if (!match) return null;
  // 从 opener 的花括号开始配平，避免"嵌套一层就截断"的脆弱正则。
  const start = source.indexOf('{', match.index);
  if (start === -1) return null;
  let depth = 0;
  for (let index = start; index < source.length; index += 1) {
    const char = source[index];
    if (char === '{') depth += 1;
    else if (char === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start + 1, index);
    }
  }
  return null;
}

describe('styles/tokens.css', () => {
  it('保留 prefers-reduced-motion 块，且含 animation/transition 的 !important', () => {
    const reducedMotion = block(css, /@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)/);
    expect(reducedMotion, '缺少 @media (prefers-reduced-motion: reduce) 块').not.toBeNull();

    // 两条 !important 是"防删"断言：没有它们，系统开启"减弱动态效果"后
    // 动画仍然照跑（这正是不该静默失败的一类可访问性问题）。
    expect(reducedMotion).toMatch(/animation-duration\s*:\s*[^;]*!important/);
    expect(reducedMotion).toMatch(/transition-duration\s*:\s*[^;]*!important/);
    expect(reducedMotion).toMatch(/animation-iteration-count\s*:\s*[^;]*!important/);
    expect(reducedMotion).toMatch(/scroll-behavior\s*:\s*auto\s*!important/);
  });

  it('声明触屏命中区 token：--tap-target: 44px', () => {
    expect(css).toMatch(/--tap-target\s*:\s*44px\s*;/);
    // 断点契约把它钉在 44：改小就会与 §3.3.1 的命中区契约不一致
    expect(css).not.toMatch(/--tap-target\s*:\s*(?:[0-3]\d|4[0-3])px\s*;/);
  });

  it('去掉触屏点击高亮块，并声明安全区变量', () => {
    expect(css).toMatch(/-webkit-tap-highlight-color\s*:\s*transparent\s*;/);
    for (const side of ['top', 'right', 'bottom', 'left']) {
      expect(css).toMatch(new RegExp(`--safe-${side}\\s*:\\s*env\\(safe-area-inset-${side}`));
    }
  });

  it('横向滚动的代码块带上 iOS 惯性滚动', () => {
    const utility = block(css, /\.rl-scroll-x\s*\{/);
    // block() 的 opener 已经吃了 `{`，所以这里单独用正则确认属性
    expect(css).toMatch(/\.rl-scroll-x\s*\{[^}]*overflow-x\s*:\s*auto/);
    expect(css).toMatch(/\.rl-scroll-x\s*\{[^}]*(-webkit-)?overflow-scrolling\s*:\s*touch/);
    expect(utility).not.toBeNull();
  });

  it('全局 32px 命中区留在 @layer base 里（否则会压掉组件的 min-h-11）', () => {
    const baseLayer = block(css, /@layer\s+base\s*\{/);
    expect(baseLayer, '缺少 @layer base { } 块').not.toBeNull();
    expect(baseLayer).toMatch(/button[\s\S]*min-height\s*:\s*32px/);

    // 无层级位置不允许再出现同样的声明：那会重新变成"最高优先级"，
    // 组件上的 `min-h-11` 会被静默压回 32px。
    const withoutBaseLayer = css.replace(baseLayer ?? '', '');
    expect(withoutBaseLayer).not.toMatch(/min-height\s*:\s*32px/);
  });
});
