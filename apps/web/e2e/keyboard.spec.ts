/**
 * T-A11Y-2 — 键盘全链路（spec §3.3.3、§7.3）——离线层，零后端。
 *
 * 六步：① 首页 Tab 可达导入框 → 开始生成；② 工作台 Tab 进大纲、Enter 切课时；
 * ③ Escape 关 sheet 且焦点回到触发按钮；④ 播放器 Space / J / K；
 * ⑤ 深度源码 Tab 进代码区（经 `?code=plain` 钉定，理由同 a11y.spec.ts）；
 * ⑥ 全程 `:focus` 不落 `body`。
 *
 * "焦点落 body"是键盘用户最致命的一种失败：接下来的 Tab 会从文档开头重新数，
 * 用户以为"页面把我踢回顶部了"。所以它被写进每一条用例里，而不是单独一条。
 */

import { expect, test, type Page } from '@playwright/test';

import { COURSE_ID, mockApi, visitConfigured } from './fixtures';

// `next dev` 首次访问某条路由要现编译（几秒到十几秒），而这三条门禁每条都要走
// 多个路由。默认 30s 在并行跑时会把"门禁"变成噪声（playwright.config.ts 的注释
// 也说明了同一件事），所以本文件自己把上限提到 120s。
test.describe.configure({ timeout: 120_000 });

const subtitleBar = (page: Page) =>
  page
    .locator('[aria-live="polite"]')
    .filter({ hasText: /本节暂无配音|配音 · 精确时间轴/ })
    .first();

/** `activeElement` 走丢了（落到 document.body / null）？ */
async function focusLostOnBody(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const element = document.activeElement;
    return !element || element === document.body;
  });
}

/**
 * Tab 直到焦点进入 `selector` 命中的子树。
 *
 * 顺带在每一次按键后检查焦点是否掉到 body——把 ⑥ 合并进 ①–⑤，
 * 这样"能 Tab 到"与"焦点没丢"是同一个动作的两面，不会出现"能到但中途丢过"。
 */
async function tabUntil(page: Page, selector: string, label: string, maxPresses = 40): Promise<void> {
  for (let press = 1; press <= maxPresses; press += 1) {
    await page.keyboard.press('Tab');
    if (await focusLostOnBody(page)) {
      throw new Error(`第 ${press} 次 Tab 之后焦点落到 body（目标：${label}）`);
    }
    const reached = await page.evaluate((sel) => {
      const element = document.activeElement as HTMLElement | null;
      if (!element) return false;
      return element.matches(sel) || Boolean(element.closest(sel));
    }, selector);
    if (reached) return;
  }
  throw new Error(`按了 ${maxPresses} 次 Tab 仍未到达「${label}」（${selector}）`);
}

test.describe('T-A11Y-2 · 键盘全链路', () => {
  test('① 首页：Tab 可达导入框，下一停是「生成学习课程」', async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, '/');

    await tabUntil(page, 'input[aria-label="GitHub 仓库地址"]', '导入框');
    await expect(page.getByRole('textbox', { name: 'GitHub 仓库地址' })).toBeFocused();

    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: /生成学习课程|正在排队/ })).toBeFocused();
    expect(await focusLostOnBody(page)).toBe(false);
  });

  test('② 工作台：Tab 进大纲，Enter 切换课时', async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, `/course/${COURSE_ID}/overview`);
    await expect(page.locator('[data-rl-transport]')).toBeVisible();

    await tabUntil(page, 'aside a[href*="lesson=2.1"]', '大纲里的「一次渲染的完整链路」');
    await page.keyboard.press('Enter');

    // Enter 必须真的换课时，而不是"焦点过去了、内容没动"
    await expect(page).toHaveURL(/lesson=2\.1/);
    expect(await focusLostOnBody(page)).toBe(false);
  });

  test('③ Escape 关闭 sheet，焦点回到触发按钮', async ({ page }) => {
    await mockApi(page);
    // 「打开大纲」只在 <lg 出现：默认 1280 视口下它根本不在 DOM 里
    await page.setViewportSize({ width: 900, height: 700 });
    await visitConfigured(page, `/course/${COURSE_ID}/overview`);

    const trigger = page.getByRole('button', { name: '打开大纲' });
    await expect(trigger).toBeVisible();
    await trigger.click();

    const sheet = page.getByRole('dialog', { name: '课程大纲' });
    await expect(sheet).toBeVisible();
    // 打开后焦点必须进面板内部，否则 Tab 会跑到遮罩下面的页面里
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))).toBe(true);

    await page.keyboard.press('Escape');
    await expect(sheet).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test('④ 播放器：Space 播放/暂停，J/K 切步', async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, `/course/${COURSE_ID}/walkthrough`);
    await expect(page.locator('[data-rl-transport]')).toBeVisible();

    // 让焦点离开任何输入控件（否则 Space 会被当成输入），但**不要点链接**
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.());

    await page.keyboard.press('Space');
    await expect(page.getByRole('button', { name: '暂停', exact: true })).toBeVisible();

    await page.keyboard.press('k');
    await expect(subtitleBar(page)).toContainText('步骤 2');

    await page.keyboard.press('j');
    await expect(subtitleBar(page)).toContainText('步骤 1');

    await page.keyboard.press('Space');
    await expect(page.getByRole('button', { name: '播放', exact: true })).toBeVisible();
  });

  test('⑤ 深度源码：Tab 进代码区（经 ?code=plain）', async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, `/course/${COURSE_ID}/deep-dive?code=plain`);

    // 深链没生效 = 这条用例在测 Monaco，焦点顺序完全不同（评审 P1-8）
    await expect(page.locator('[data-code-view="plain"]')).toBeVisible();

    await tabUntil(page, '[data-code-view="plain"]', '只读代码视图');
    await expect(page.locator('[data-code-view="plain"]')).toBeFocused();
    expect(await focusLostOnBody(page)).toBe(false);
  });

  test('⑥ 全程无焦点丢失：按可达元素个数连续 Tab，不落 body', async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, '/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // 只 Tab 到"最后一个可达元素"为止：再往后按一次，Chromium 会把焦点交给浏览器
    // 外壳（`document.activeElement` 变成 body），那是**正常行为**，不是缺陷。
    // 把它当成失败会让这条门禁永远红，然后被人删掉。
    const focusables = await page.evaluate(() =>
      Array.from(
        document.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.offsetParent !== null || element.getClientRects().length > 0).length,
    );
    expect(focusables, '首页上没有任何可聚焦元素').toBeGreaterThan(3);

    for (let press = 1; press <= focusables; press += 1) {
      await page.keyboard.press('Tab');
      expect(await focusLostOnBody(page), `第 ${press}/${focusables} 次 Tab 之后焦点落到 body`).toBe(false);
    }
  });
});
