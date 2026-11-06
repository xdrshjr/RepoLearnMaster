/**
 * T-A11Y-1 / T-A11Y-4 — axe 门禁（spec §3.3.3、§7.3、§7.7 A4）——离线层，零后端。
 *
 * 为什么 deep-dive 一律经 `?code=plain` 打开（评审 P1-8 / §10 第 10 条）：
 * 代码面板会在离线时 4.5s 后从 Monaco 回落到 `PlainCodeView`，**同一份断言在两种
 * DOM 下会得出不同结论**。深链把"测的是哪一份 DOM"从运气变成前提，所以每次扫描前
 * 先断言 `[data-code-view="plain"]` 真的在——否则说明深链没生效，用例在测另一条路径。
 *
 * 为什么 `.monaco-editor` 排除：Monaco 的内部控件（对比度、aria-*）不归我们修，
 * 把它算进 "serious = 0" 等于让门禁在构造上永远红，最后一定被人删掉。真正该守的是
 * 我们自己的控件，T-A11Y-4 单独覆盖（它同样排除 Monaco 子树）。
 *
 * moderate|minor 不是"随便过"：每一条都必须登记在 `e2e/a11y-baseline.json` 里并写明
 * reason，未登记的严重度同样判失败——否则"基线"就会变成垃圾桶。
 */

import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

import baseline from './a11y-baseline.json';
import { COURSE_ID, fulfilJson, mockApi, visitConfigured } from './fixtures';

// 每条用例至少一次整页 axe 分析 + 一次 dev 编译；30s 默认值会把门禁变成噪声。
test.describe.configure({ timeout: 120_000 });

const BOOK_ID = 'bk_demo01';
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

/** Emulating axe-core's result shape locally keeps the test free of extra deps. */
interface AxeNode {
  target: Array<string | string[]>;
  html?: string;
  failureSummary?: string;
}
interface AxeViolation {
  id: string;
  impact?: 'minor' | 'moderate' | 'serious' | 'critical' | null;
  help: string;
  nodes: AxeNode[];
}

interface BaselineEntry {
  rule: string;
  selector: string;
  reason: string;
}

const baselineFile = baseline as unknown as {
  excludes?: Array<{ selector: string; reason?: string }>;
  entries?: BaselineEntry[];
};

const EXCLUDES = baselineFile.excludes ?? [];
const ENTRIES = baselineFile.entries ?? [];

/** Books are not part of the shared fixture set, so `/book/<demo>` is mocked here. */
const bookDetail = {
  id: BOOK_ID,
  course_version_id: COURSE_ID,
  preset: 'standard',
  status: 'ready',
  title: 'React 带读课程 · 书籍版',
  chapters: [
    { key: 'ch_1', title: '第一章 · 宏观架构', words: 1200 },
    { key: 'ch_2', title: '第二章 · 全局走读', words: 900 },
  ],
  toc: [],
  quality: { anchor_coverage: 0.9 },
  word_count: 2100,
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
  // Registered *after* `mockApi`'s catch-all: Playwright matches routes LIFO,
  // so this override wins for `/api/books/**` (same trick as learning.spec.ts).
  await page.route('**/api/books/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (/^\/api\/books\/[^/]+$/.test(path)) {
      await fulfilJson(route, bookDetail);
      return;
    }
    if (/^\/api\/books\/[^/]+\/chapters\/[^/]+$/.test(path)) {
      await fulfilJson(route, bookChapter);
      return;
    }
    await fulfilJson(route, bookDetail);
  });
}

function targetOf(node: AxeNode): string {
  return node.target.map((part) => (Array.isArray(part) ? part.join(' ') : part)).join(' ');
}

function baselineEntryFor(violation: AxeViolation, node: AxeNode): BaselineEntry | undefined {
  const target = targetOf(node);
  return ENTRIES.find(
    (entry) =>
      entry.rule === violation.id &&
      Boolean(entry.reason) &&
      Boolean(entry.selector) &&
      target.includes(entry.selector),
  );
}

function describeViolations(items: Array<{ violation: AxeViolation; node: AxeNode }>): string {
  return items
    .map(({ violation, node }) => {
      // `failureSummary` 是 axe 给出的实证（例如 "insufficient color contrast of 3.1
      // (foreground: #6d837c, background: #161d1b)"）——没有它，改的人只能靠猜。
      const detail = (node.failureSummary ?? '').replace(/\s+/g, ' ').trim();
      return `- [${violation.impact ?? 'unknown'}] ${violation.id} @ ${targetOf(node)} — ${detail || violation.help}`;
    })
    .join('\n');
}

async function scan(page: Page) {
  let builder = new AxeBuilder({ page }).withTags(TAGS);
  for (const exclude of EXCLUDES) {
    builder = builder.exclude(exclude.selector);
  }
  return (await builder.analyze()) as unknown as { violations: AxeViolation[] };
}

/**
 * T-A11Y-1 的核心断言：`serious|critical` 必须为 0；`moderate|minor` 必须已登记。
 */
async function expectAccessible(page: Page, label: string): Promise<void> {
  const results = await scan(page);
  const findings = results.violations.flatMap((violation) =>
    violation.nodes.map((node) => ({ violation, node })),
  );

  const serious = findings.filter(
    ({ violation }) => violation.impact === 'serious' || violation.impact === 'critical',
  );
  expect(
    serious.length,
    `${label}: serious/critical 必须为 0，实际 ${serious.length} 条\n${describeViolations(serious)}`,
  ).toBe(0);

  const unregistered = findings.filter(
    ({ violation, node }) =>
      (violation.impact === 'moderate' || violation.impact === 'minor') &&
      !baselineEntryFor(violation, node),
  );
  expect(
    unregistered.length,
    `${label}: 有 ${unregistered.length} 条未登记的 moderate/minor 违反项；`
      + `要么修掉，要么按 {"rule","selector","reason"} 登记到 e2e/a11y-baseline.json\n`
      + describeViolations(unregistered),
  ).toBe(0);
}

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('load');
  // 字体加载会改变文本度量，不影响 axe 的对比度结论，但它让"扫描时间点"可复现。
  await page.evaluate(() => (document.fonts ? document.fonts.ready.then(() => undefined) : undefined));
}

const DEEP_DIVE_PLAIN = `/course/${COURSE_ID}/deep-dive?code=plain`;

test.describe('T-A11Y-1 · 6 条路由的 axe 门禁', () => {
  test('baseline 的每一条都有 reason（防止白名单变成垃圾桶）', () => {
    for (const entry of ENTRIES) {
      expect(entry.reason?.trim(), `基线条目缺少 reason：${JSON.stringify(entry)}`).toBeTruthy();
      expect(entry.rule?.trim(), `基线条目缺少 rule：${JSON.stringify(entry)}`).toBeTruthy();
      expect(entry.selector?.trim(), `基线条目缺少 selector：${JSON.stringify(entry)}`).toBeTruthy();
    }
    for (const exclude of EXCLUDES) {
      expect(exclude.reason?.trim(), `排除项缺少 reason：${JSON.stringify(exclude)}`).toBeTruthy();
    }
  });

  test('/ 首页', async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, '/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await settle(page);
    await expectAccessible(page, 'home');
  });

  test('/setup 配置向导', async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, '/setup');
    await expect(page.locator('#main')).toBeVisible();
    await settle(page);
    await expectAccessible(page, 'setup');
  });

  test('/settings 设置', async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, '/settings');
    await expect(page.getByRole('heading', { name: '设置' })).toBeVisible();
    await settle(page);
    await expectAccessible(page, 'settings');
  });

  test(`/course/${COURSE_ID}/overview 宏观架构`, async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, `/course/${COURSE_ID}/overview`);
    await expect(page.locator('[data-rl-transport]')).toBeVisible();
    await settle(page);
    await expectAccessible(page, 'overview');
  });

  test('deep-dive 一律经 ?code=plain 打开', async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, DEEP_DIVE_PLAIN);
    // 深链没生效就意味着"这条用例在测 Monaco"，而 Monaco 在离线层根本不该出现。
    await expect(page.locator('[data-code-view="plain"]')).toBeVisible();
    await settle(page);
    await expectAccessible(page, 'deep-dive(plain)');
  });

  test(`/book/${BOOK_ID} 课程书籍`, async ({ page }) => {
    await mockApi(page);
    await mockBooks(page);
    await visitConfigured(page, `/book/${BOOK_ID}`);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await settle(page);
    await expectAccessible(page, 'book');
  });
});

/**
 * T-A11Y-4 — "Monaco 真的挂起来时，我们自己的控件是否可访问"。
 *
 * 唯一允许的 skip（spec §7.3）：离线层拿不到 AMD loader，编辑器在 4.5s 内不会就绪；
 * 这时本用例 skip 并打印原因——它测的是"我们有没有把可访问性做在**自己的**控件上"，
 * 而不是"Monaco 好不好"。门禁本身仍然排除 Monaco 子树（见文件头）。
 */
test.describe('T-A11Y-4 · Monaco 就绪时只断言我们自己的控件', () => {
  test('monaco when available', async ({ page }) => {
    await mockApi(page);
    await visitConfigured(page, `/course/${COURSE_ID}/deep-dive?code=monaco`);

    const editor = page.locator('.monaco-editor');
    let ready = false;
    try {
      // 比 code-pane 自己的 4.5s 回落阈值宽松，是因为 `next dev` 首次编译这条路由
      // 就要好几秒——用 4.5s 会让本用例在开发机上**永远** skip，那等于没测。
      await editor.waitFor({ state: 'attached', timeout: 25_000 });
      // Monaco 的无障碍编辑上下文只有在编辑器真正挂载后才存在（learning.spec.ts 同款）
      await page.getByRole('textbox', { name: 'Editor content' }).waitFor({ state: 'attached', timeout: 25_000 });
      ready = true;
    } catch {
      ready = false;
    }

    test.skip(
      !ready,
      '离线层无法加载 Monaco AMD loader（4.5s 内未就绪）：本用例测的是我们自己的控件，Monaco 由 T-A11Y-1 的排除项覆盖',
    );

    await settle(page);
    await expectAccessible(page, 'deep-dive(monaco)');
  });
});
