/**
 * T-SEARCH-8 — 搜索的用户可见闭环（spec §7.4 / §3.4.4）——离线层，零后端。
 *
 * 四条断言对应四件**用户会真的遇到**的事，且每一条都挑了"最容易写成假通过"
 * 的那个版本去写：
 *
 *  ① 输入 ≥3 字 → 命中并渲染 `<mark>`（高亮是 React 元素生成的，服务端只回切段）；
 *  ② 输入 2 字 → 出现"查询短于 3 字"提示，且**列表不为空**。这条最容易写成
 *     "有提示就行"：真正的故障形态（G3/F15）恰恰是"有提示、列表空"，也就是
 *     用户搜了个 2 字词，界面很礼貌地告诉他"已按时间列出"，然后什么都没有；
 *  ③ `/` 键聚焦搜索框（且焦点本来就在输入框里时不抢按键）；
 *  ④ 空结果有明确空态文案，而不是一片空白。
 *
 * 后端用 `page.route` 顶替：`mockApi` 的 catch-all 之后注册一个更具体的
 * `/api/courses` 覆盖（Playwright 路由是 LIFO），按 `q` 的长度返回与
 * `CourseListResponse` 完全一致的两条分支（`mode` / `fallback_reason` / `highlights`）。
 */

import { expect, test, type Page } from '@playwright/test';

import { COURSE_ID, courseDetail, fulfilJson, mockApi, visitConfigured } from './fixtures';

const SEARCH_BOX = '搜索课程';
const RESULTS = '[data-rl-search-results]';

/** 一条带高亮切段的搜索结果：`marked` 的片段必须被渲染成 `<mark>`。 */
const highlightedItem = {
  ...courseDetail,
  id: COURSE_ID,
  title: 'React 带读：Agent 如何对话',
  highlights: {
    title: [
      { text: 'React 带读：', marked: false },
      { text: 'Agent', marked: true },
      { text: ' 如何对话', marked: false },
    ],
    summary: [{ text: '这是一门讲 Agent 编排的课。', marked: true }],
    repo: null,
  },
};

/** 2 字查询走 scan：**有结果**，只是排序退回创建时间（`fallback_reason`）。 */
const scanResponse = (q: string) => ({
  items: [courseDetail],
  mode: 'scan',
  fallback_reason: 'query_too_short',
  next_cursor: null,
  next_offset: null,
  total: null,
});

/** ≥3 字查询走 fts：带 `total`、`highlights`，`next_cursor` 恒为 null。 */
const ftsResponse = (items: unknown[], total: number) => ({
  items,
  mode: 'fts',
  fallback_reason: null,
  next_cursor: null,
  next_offset: null,
  total,
});

/**
 * `/api/courses` GET 的搜索分支。
 *
 * 只接管"带 q 的 GET"：其余请求（首页热门课程、创建课程）原样 fallback 给
 * `fixtures.mockApi`，这样本文件不需要重复维护一整套夹具。
 */
async function mockSearch(page: Page): Promise<{ queries: string[] }> {
  const queries: string[] = [];
  await mockApi(page);
  await page.route('**/api/courses**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname !== '/api/courses' || request.method() !== 'GET') return route.fallback();

    const q = (url.searchParams.get('q') ?? '').trim();
    if (!q) return route.fallback();
    queries.push(q);

    if (q.length < 3) {
      await fulfilJson(route, scanResponse(q));
      return;
    }
    if (q.includes('空')) {
      await fulfilJson(route, ftsResponse([], 0));
      return;
    }
    await fulfilJson(route, ftsResponse([highlightedItem], 1));
  });
  return { queries };
}

const searchBox = (page: Page) => page.getByRole('textbox', { name: SEARCH_BOX });

test('① 输入 ≥3 字命中并渲染 <mark> 高亮', async ({ page }) => {
  const { queries } = await mockSearch(page);
  await visitConfigured(page, '/');

  await searchBox(page).fill('Agent');
  // 300ms 防抖之后才发请求；`expect` 自带重试，不要用 waitForTimeout 猜时间。
  await expect(page.locator(RESULTS)).toBeVisible();

  const results = page.locator(RESULTS);
  const mark = results.locator('mark').first();
  await expect(mark).toBeVisible();
  await expect(mark).toHaveText('Agent');

  // 高亮是切段渲染出来的：未命中的片段仍在（不是一个只剩关键词的标签）
  await expect(results.getByText('React 带读：')).toBeVisible();

  // 模式提示讲的是"实际生效"的模式，不是配置值
  await expect(page.getByText('全文索引（≥3 字）')).toBeVisible();
  // 播报：结果区的 role="status" 里必须有条数
  await expect(results).toContainText('找到 1 门课');

  expect(queries).toContain('Agent');
  // 只有一份请求真正带着 q 发出去（防抖 + keepPreviousData 不应把每键都打一遍）
  expect(queries.filter((value) => value === 'Agent').length).toBe(1);
});

test('② 输入 2 字出现"短于 3 字"提示，且列表不为空', async ({ page }) => {
  await mockSearch(page);
  await visitConfigured(page, '/');

  await searchBox(page).fill('缓存');
  const results = page.locator(RESULTS);
  await expect(results).toBeVisible();

  // 提示必须在（说明后端诚实回显了 fallback_reason）
  await expect(page.getByText('按创建时间列出（查询短于 3 字，索引不适用）')).toBeVisible();
  await expect(results.getByText(/短于 3 字/)).toBeVisible();

  // **关键断言**：列表不为空。2 字查询在 trigram 下会静默返回 0 行，
  // 如果这条只断言"有提示"，那个故障形态会 100% 通过。
  await expect(results.getByRole('link', { name: /开始学习/ })).toBeVisible();
  await expect(results).toContainText('找到 1 门课');
});

test('③ `/` 键聚焦搜索框', async ({ page }) => {
  await mockSearch(page);
  await visitConfigured(page, '/');

  // 焦点先离开输入框（初始焦点就是 body，这里显式加一步，避免依赖浏览器差异）
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.());
  await expect(searchBox(page)).not.toBeFocused();

  await page.keyboard.press('/');
  await expect(searchBox(page)).toBeFocused();

  // 焦点已经在输入框里时，`/` 是**字符**而不是快捷键（不能把用户想搜的 "/" 吃掉）
  await page.keyboard.press('/');
  await expect(searchBox(page)).toHaveValue('/');
});

test('④ 空结果有明确空态文案', async ({ page }) => {
  await mockSearch(page);
  await visitConfigured(page, '/');

  await searchBox(page).fill('空仓查询');
  const results = page.locator(RESULTS);
  await expect(results).toBeVisible();

  await expect(results.getByText('没有找到匹配「空仓查询」的课程')).toBeVisible();
  await expect(results.getByText(/换一个更短的关键词/)).toBeVisible();
  // 空态里不能残留任何课程卡片
  await expect(results.getByRole('link', { name: /开始学习/ })).toHaveCount(0);
});
