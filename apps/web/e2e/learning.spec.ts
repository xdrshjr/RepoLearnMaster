/**
 * 学习闭环（spec §7.3–§7.6 / §8.3）——离线。
 *
 * 覆盖的是"播放器 + 字幕 + 只读 IDE + 答题 + 完课"这条主链路里最容易静默
 * 坏掉的三处：
 *  · 没有音频时必须走 estimated 推进（有音频时靠 `audio.currentTime`）；
 *  · 切步之后字幕跟着换（步骤与字幕是一对多）；
 *  · 答题提交后必须给出解释，并标注是否为重复提交。
 *
 * 选择器说明：字幕条与 Momo 侧栏都会讲同一句话，因此字幕断言必须**限定到
 * 字幕条**（含"步骤 N"的那一块），否则会变成"侧栏里有这段文字就算过"。
 */

import { expect, test } from '@playwright/test';

import { COURSE_ID, LESSON_KEY, fulfilJson, mockApi, visitConfigured } from './fixtures';

const FIRST_SEGMENT = '这是第一段字幕：先看仓库的顶层目录。';
const SECOND_STEP_SEGMENT = '入口文件是 src/App.js。';

const subtitleBar = (page: import('@playwright/test').Page) =>
  page
    .locator('[aria-live="polite"]')
    // 字幕条独有的徽标文案：侧栏也有"当前步骤"的 aria-live，按"步骤 N"过滤会选中它
    .filter({ hasText: /本节暂无配音|配音 · 精确时间轴/ })
    .first();

test('第一层：课程外壳、课时标题与字幕同时就位', async ({ page }) => {
  await mockApi(page);
  await visitConfigured(page, `/course/${COURSE_ID}/overview`);
  await expect(page.getByRole('heading', { name: 'React 带读课程' })).toBeVisible();
  await expect(subtitleBar(page)).toContainText(FIRST_SEGMENT);
});

test('播放器：没有音频时按 estimated 推进，切步后字幕跟着换', async ({ page }) => {
  await mockApi(page);
  await visitConfigured(page, `/course/${COURSE_ID}/walkthrough`);

  const play = page.getByRole('button', { name: '播放', exact: true });
  await expect(play).toBeVisible();
  await play.click();
  await expect(page.getByRole('button', { name: '暂停', exact: true })).toBeVisible();

  await page.getByRole('button', { name: '下一步', exact: true }).click();
  await expect(subtitleBar(page)).toContainText('步骤 2');
  await expect(subtitleBar(page)).toContainText(SECOND_STEP_SEGMENT);
});

test('只读 IDE：Monaco 真的挂起来了（编辑区存在 + 面包屑指向文件）', async ({ page }) => {
  await mockApi(page);
  await visitConfigured(page, `/course/${COURSE_ID}/deep-dive`);
  // Monaco 的无障碍编辑区在无头环境里是 0 尺寸的原生编辑上下文，因此断言"存在"
  await expect(page.getByRole('textbox', { name: 'Editor content' })).toBeAttached({ timeout: 20_000 });
  await expect(page.getByText('只读', { exact: true })).toBeVisible();
  // 降级提示不应出现：它一出现就说明 Monaco 没起来
  await expect(page.getByText('Monaco 不可用')).toHaveCount(0);
});

test('答题：提交后给出解释', async ({ page }) => {
  await mockApi(page);
  await visitConfigured(page, `/course/${COURSE_ID}/walkthrough`);
  await page.getByRole('button', { name: '下一步', exact: true }).click();

  // 选项的可访问名是 "a src/App.js"（字母 + 文本），精确匹配才不会点到侧栏证据按钮
  await page.getByRole('button', { name: 'a src/App.js', exact: true }).click();
  await expect(page.getByText('对，App.js 是入口。')).toBeVisible();
});

test('答题接口返回 replayed 时，界面明确说明"重复提交"', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/courses/*/quiz/*/answer', async (route) => {
    await fulfilJson(route, {
      correct: true,
      explanation_md: '对，App.js 是入口。',
      evidence: [],
      replayed: true,
    });
  });
  await visitConfigured(page, `/course/${COURSE_ID}/walkthrough`);
  await page.getByRole('button', { name: '下一步', exact: true }).click();
  await page.getByRole('button', { name: 'a src/App.js', exact: true }).click();
  await expect(page.getByText(/重复提交/)).toBeVisible();
});

test('完课页：知识回顾、能力雷达与"生成课程书籍"入口', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/courses/*/books', async (route) => {
    await fulfilJson(route, { book_id: 'bk_demo01', job_id: 'job_book01', reused: false }, 202);
  });
  await visitConfigured(page, `/course/${COURSE_ID}/recap`);
  await expect(page.getByText('知识点复盘').first()).toBeVisible();
  await expect(page.getByText('不要把 reconciler 与 renderer 混为一谈')).toBeVisible();
  await expect(page.getByRole('img', { name: /五维能力/ })).toBeVisible();

  await page.getByRole('button', { name: '生成课程书籍' }).click();
  await expect(page).toHaveURL(/\/book\/bk_demo01/);
});

test('深链带 lesson 参数时打开指定课时（不白屏）', async ({ page }) => {
  await mockApi(page);
  await visitConfigured(page, `/course/${COURSE_ID}/overview?lesson=${LESSON_KEY}`);
  await expect(subtitleBar(page)).toContainText(FIRST_SEGMENT);
});
