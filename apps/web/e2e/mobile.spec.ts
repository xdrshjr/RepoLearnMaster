/**
 * T-TOUCH-1..4 — 窄屏 / 触屏门禁（spec §3.3.1、§3.3.2、§7.3）——离线层，零后端。
 *
 * 三个视口各跑一次「首页 → 课程 → 首步 → 深度源码」：
 *  · 390×844  （iPhone 12）—— 真正的手机宽度；
 *  · 768×1024 （iPad 竖）  —— `md` 断点，表格/矩阵在这里必须已经变成卡片；
 *  · 1024×768 （笔记本）   —— `lg` 断点，桌面密度，不参与命中区断言。
 *
 * 三条断言分别是三件不同的事，不能合成一条：
 *  1) `documentElement.scrollWidth ≤ clientWidth + 1` —— 整页不横向滚动；
 *  2) `getByRole('toolbar')` 四边在视口内，且**顶边在选区底边下方 ≤120px** ——
 *     D29 的分界线：只断言"在视口内"会放过"贴在面板左上角、跟选区无关"的实现；
 *  3) `[data-rl-tap]:visible` 的命中区 ≥43.5 —— 只遍历**显式登记**的主要动作，
 *     不遍历 `button`/`a`（那会把 Monaco 注入的 16px 控件与 `height=0` 的隐藏元素
 *     算进来，门禁第一天就红，随后必然被删；评审 P1-7）。
 *
 * 深度源码一律 `?code=plain` 打开：Monaco 在离线层的就绪与否取决于网络，
 * 两态混进同一条门禁等于随机红（§3.3.3 / §10 第 10 条）。
 */

import { expect, test, type Page } from '@playwright/test';

import { COURSE_ID, fulfilJson, mockApi, visitConfigured } from './fixtures';

// 每个视口矩阵要跑 5 条路由 × 3 类断言，dev 编译 + axe 之外还要拖选；
// 默认 30s 会让"慢"变成"红"，那是最容易被删掉的那种门禁。
test.describe.configure({ timeout: 180_000 });

const BOOK_ID = 'bk_demo01';
const DEEP_DIVE_PLAIN = `/course/${COURSE_ID}/deep-dive?code=plain`;
const TAP_MIN = 43.5; // 留 0.5 子像素容差（§7.3 T-TOUCH-4）

/** Books are not part of the shared fixture set — mocked locally (same as a11y.spec.ts). */
const bookDetail = {
  id: BOOK_ID,
  course_version_id: COURSE_ID,
  preset: 'standard',
  status: 'ready',
  title: 'React 带读课程 · 书籍版',
  chapters: [{ key: 'ch_1', title: '第一章 · 宏观架构', words: 1200 }],
  toc: [],
  quality: {},
  word_count: 1200,
};

const bookChapter = {
  key: 'ch_1',
  title: '第一章 · 宏观架构',
  blocks: [
    { type: 'md', text: '## 目录骨架\n\n先把顶层目录看一遍，再进入入口文件。' },
    { type: 'code', text: 'function App() {\n  return null;\n}\n', lang: 'javascript', caption: 'src/App.js' },
    { type: 'table', text: '目录            作用\nsrc             源码\npackage.json    依赖声明' },
  ],
  source_refs: [{ file: 'src/App.js', line_start: 1, line_end: 3 }],
};

async function mockBooks(page: Page): Promise<void> {
  await page.route('**/api/books/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (/^\/api\/books\/[^/]+\/chapters\/[^/]+$/.test(path)) {
      await fulfilJson(route, bookChapter);
      return;
    }
    await fulfilJson(route, bookDetail);
  });
}

const ROUTES: Array<{ name: string; path: string; withBook?: boolean }> = [
  { name: '首页', path: '/' },
  { name: '课程总览（首步）', path: `/course/${COURSE_ID}/overview` },
  { name: '全局走读', path: `/course/${COURSE_ID}/walkthrough` },
  { name: '深度源码(?code=plain)', path: DEEP_DIVE_PLAIN },
  // D31 的另一半：设置页的宽表（角色矩阵）在 `<md` 必须已经变成 `<dl>` 卡片，
  // 否则这里会以"整页横向滚动"的形式立刻变红。
  { name: '设置（响应式表格）', path: '/settings' },
  { name: '课程书籍', path: `/book/${BOOK_ID}`, withBook: true },
];

const VIEWPORTS = [
  { label: '390x844 · iPhone 12', width: 390, height: 844, taps: true },
  { label: '768x1024 · iPad 竖', width: 768, height: 1024, taps: true },
  { label: '1024x768 · 笔记本', width: 1024, height: 768, taps: false },
];

async function openRoute(page: Page, route: (typeof ROUTES)[number]): Promise<void> {
  await mockApi(page);
  if (route.withBook) await mockBooks(page);
  await visitConfigured(page, route.path);
  await expect(page.locator('#main, main').first()).toBeVisible();
  await page.waitForLoadState('load');
}

for (const viewport of VIEWPORTS) {
  test.describe(viewport.label, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height }, hasTouch: true });

    test('T-TOUCH-2 · 任何一层都不产生横向滚动', async ({ page }) => {
      for (const route of ROUTES) {
        await openRoute(page, route);
        const metrics = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
        }));
        expect(
          metrics.scrollWidth,
          `${route.name} 在 ${viewport.label} 下横向溢出：scrollWidth=${metrics.scrollWidth} > clientWidth=${metrics.clientWidth}`,
        ).toBeLessThanOrEqual(metrics.clientWidth + 1);
      }
    });

    test('T-TOUCH-1 · 选区工具条留在视口内，且跟着选区走', async ({ page }) => {
      await openRoute(page, ROUTES[3]!);
      await expect(page.locator('[data-code-view="plain"]')).toBeVisible();

      // 行号列是 `select-none`，从那里按下拖拽不会产生选区；必须从代码文本 span 起手。
      const lineText = (line: number) =>
        page.locator(`[data-code-view="plain"] [data-line="${line}"] > span:nth-child(2)`);
      const firstText = lineText(1);
      const secondText = lineText(2);
      await expect(firstText).toBeVisible();
      const firstBox = await firstText.boundingBox();
      const secondBox = await secondText.boundingBox();
      expect(firstBox).not.toBeNull();
      expect(secondBox).not.toBeNull();

      // 真实拖选（工具条的锚点来自 `Range.getBoundingClientRect()`，用 selectText 造不出来）
      await page.mouse.move(firstBox!.x + 6, firstBox!.y + firstBox!.height / 2);
      await page.mouse.down();
      await page.mouse.move(
        secondBox!.x + Math.min(60, secondBox!.width / 2),
        secondBox!.y + secondBox!.height / 2,
        { steps: 10 },
      );
      await page.mouse.up();

      const toolbar = page.getByRole('toolbar');
      await expect(toolbar).toBeVisible();

      const box = await toolbar.boundingBox();
      expect(box, '工具条没有 boundingBox').not.toBeNull();
      expect(box!.x, `工具条左边越界：${JSON.stringify(box)}`).toBeGreaterThanOrEqual(-0.5);
      expect(box!.y, `工具条上边越界：${JSON.stringify(box)}`).toBeGreaterThanOrEqual(-0.5);
      expect(box!.x + box!.width, `工具条右边越界：${JSON.stringify(box)}`).toBeLessThanOrEqual(
        viewport.width + 1,
      );
      expect(box!.y + box!.height, `工具条下边越界：${JSON.stringify(box)}`).toBeLessThanOrEqual(
        viewport.height + 1,
      );

      const selectionBottom = await page.evaluate(() => {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0) return null;
        return selection.getRangeAt(0).getBoundingClientRect().bottom;
      });
      expect(selectionBottom, '拖选之后没有活动选区').not.toBeNull();
      expect(
        box!.y - (selectionBottom as number),
        `工具条没有贴着选区：toolbar.top=${box!.y}, selection.bottom=${selectionBottom}（D29 要求 ≤120）`,
      ).toBeLessThanOrEqual(120);
    });

    test('T-TOUCH-3 · <xl 深度源码页用三段切换（代码 / 执行 / 提问）', async ({ page }) => {
      test.skip(
        viewport.width >= 1280,
        '≥xl（1280px）走双栏、不渲染 pane-switcher（§3.3.1 的断点是 xl）；这一条只钉窄屏',
      );

      await openRoute(page, ROUTES[3]!);

      const tablist = page.getByRole('tablist', { name: '深度源码视图' });
      await expect(tablist).toBeVisible();
      await expect(tablist.getByRole('tab')).toHaveCount(3);

      // 点「提问」→ textarea 必须**自动获焦**。窄屏下"点了提问还得自己找输入框"
      // 是这条链路最容易掉的一环，所以断言的是焦点，而不是"面板出现了"。
      await tablist.getByRole('tab', { name: '提问' }).click();
      await expect(tablist.getByRole('tab', { name: '提问' })).toHaveAttribute('aria-selected', 'true');
      const textarea = page.locator('[data-pane-panel="ask"] textarea').first();
      await expect(textarea).toBeVisible();
      await expect(textarea).toBeFocused();

      // 切回「代码」→ 代码视图仍在（三段是"挂载 + 切可见性"，不是卸载重建，
      // 否则 CodePane 的锚点会丢、工具条退回固定偏移）
      await tablist.getByRole('tab', { name: '代码' }).click();
      await expect(page.locator('[data-code-view]')).toBeVisible();
    });

    test('T-TOUCH-4 · 主要动作命中区 ≥ 44px', async ({ page }) => {
      test.skip(
        !viewport.taps,
        '桌面视口不参与：桌面下限是 28px（§3.3.1 命中区契约），把桌面也算进来会让工具栏变成一堵墙',
      );

      await openRoute(page, ROUTES[3]!);

      // 只遍历**显式登记**的 `[data-rl-tap]`；Monaco 子树显式排除（T-TOUCH-4 要求）。
      const taps = page.locator('[data-rl-tap]:visible:not(.monaco-editor *)');
      const boxes = await taps.evaluateAll((nodes) =>
        nodes.map((node) => {
          const rect = (node as HTMLElement).getBoundingClientRect();
          const label = (
            node.getAttribute('aria-label') ??
            (node as HTMLElement).textContent ??
            node.tagName
          )
            .trim()
            .slice(0, 32);
          return { label, width: rect.width, height: rect.height };
        }),
      );

      // 一条都没有说明"登记本身"坏了（不是"刚好没有主要动作"）——所以不许删这条断言。
      expect(
        boxes.length,
        '当前视口下一条 [data-rl-tap] 都没找到：说明"哪些元素进了命中区门禁"的登记坏了',
      ).toBeGreaterThan(0);

      const tooSmall = boxes.filter((box) => box.width < TAP_MIN || box.height < TAP_MIN);
      expect(
        tooSmall,
        `${viewport.label} 下有 ${tooSmall.length} 个主要动作命中区不足 44px：\n${tooSmall
          .map((box) => `- "${box.label}" ${box.width.toFixed(1)}×${box.height.toFixed(1)}`)
          .join('\n')}`,
      ).toEqual([]);
    });
  });
}
