/**
 * 首页导入（spec §7.2 / §8.3）——离线，GitHub 与后端全部由 `page.route` 顶替。
 *
 * 断言点选的是"用户真的会遇到的四种结局"：
 *  · 合法 URL → 进准备页并带上 job；
 *  · 非法输入 → 就地内联报错，不发请求；
 *  · 同一份内容已有任务 → 409 `JOB_CONFLICT`，直接跳去那个 job；
 *  · 私有仓库 → 403 `REPO_FORBIDDEN`，给出可执行的下一步。
 */

import { expect, test } from '@playwright/test';

import { courseDetail, fulfilJson, mockApi, visitConfigured } from './fixtures';

const URL_INPUT = 'https://github.com/owner/repo';
const SUBMIT = '生成学习课程';

test('粘贴合法仓库地址后进入准备页并带上 job_id', async ({ page }) => {
  let posted: Record<string, unknown> | null = null;
  await mockApi(page);
  await page.route('**/api/courses', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    posted = route.request().postDataJSON() as Record<string, unknown>;
    await fulfilJson(route, { course_id: 'cv_demo01', job_id: 'job_demo01', status_url: '/v1/jobs/job_demo01' }, 202);
  });

  await visitConfigured(page, '/');
  await page.getByLabel('GitHub 仓库地址').fill(URL_INPUT);
  await expect(page.getByText('已解析：owner/repo')).toBeVisible();
  await page.getByRole('button', { name: SUBMIT }).click();

  await expect(page).toHaveURL(/\/repo\/owner\/repo\?job=job_demo01/, { timeout: 20_000 });
  expect(posted).not.toBeNull();
  expect(String(posted!['repo_url'])).toContain('github.com/owner/repo');
});

test('非法地址就地报错，不发出任何 /api/courses 请求', async ({ page }) => {
  let posts = 0;
  await mockApi(page);
  await page.route('**/api/courses', async (route) => {
    if (route.request().method() === 'POST') posts += 1;
    return route.fallback();
  });

  await visitConfigured(page, '/');
  await page.getByLabel('GitHub 仓库地址').fill('https://gitlab.com/owner/repo');
  // 非法输入没有"已解析"提示，改用输入框的 aria-invalid 等 hydration
  await expect(page.getByLabel('GitHub 仓库地址')).toHaveValue('https://gitlab.com/owner/repo');
  await page.getByRole('button', { name: SUBMIT }).click();

  await expect(page.getByText('目前只支持 github.com 的公开仓库')).toBeVisible();
  expect(posts).toBe(0);
});

test('同一份内容已有任务时按 JOB_CONFLICT 直接跳到那个 job', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/courses', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    await fulfilJson(
      route,
      {
        error: {
          code: 'JOB_CONFLICT',
          message: '同一份内容已有一个任务在排队或运行',
          hint: '直接打开返回的 job_id 查看进度',
          retryable: false,
          details: { job_id: 'job_demo01' },
        },
      },
      409,
    );
  });

  await visitConfigured(page, '/');
  await page.getByLabel('GitHub 仓库地址').fill(URL_INPUT);
  await expect(page.getByText('已解析：owner/repo')).toBeVisible();
  await page.getByRole('button', { name: SUBMIT }).click();

  await expect(page).toHaveURL(/\/repo\/owner\/repo\?job=job_demo01/, { timeout: 20_000 });
});

test('私有仓库返回可执行的 403 提示', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/courses', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    await fulfilJson(
      route,
      {
        error: {
          code: 'REPO_FORBIDDEN',
          message: '这个仓库是私有的或已被封禁。',
          hint: 'MVP 只支持公开仓库',
          retryable: false,
        },
      },
      403,
    );
  });

  await visitConfigured(page, '/');
  await page.getByLabel('GitHub 仓库地址').fill(URL_INPUT);
  await expect(page.getByText('已解析：owner/repo')).toBeVisible();
  await page.getByRole('button', { name: SUBMIT }).click();

  await expect(page.getByText(/REPO_FORBIDDEN/).first()).toBeVisible();
});

test('首页课程卡片可以进工作台', async ({ page }) => {
  await mockApi(page);
  await visitConfigured(page, '/');
  await expect(page.getByText('最近学习').first()).toBeVisible();
  const link = page.getByRole('link', { name: new RegExp(courseDetail.title) }).first();
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/\/course\/cv_demo01/, { timeout: 20_000 });
});
