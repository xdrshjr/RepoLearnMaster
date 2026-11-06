/**
 * 首启守卫（T-E2E-2，spec §3.6.1 / §8.3）——离线，不碰后端。
 *
 * 两条断言分别对应一个曾经出现过的真实故障：
 *  1. 没有 `rl_setup` cookie 时必须 307 到 `/setup`（否则用户进到空工作台）；
 *  2. API 不可达时 `/setup` 必须显示"后端未就绪"，**不能**再重定向
 *     （v1 的 server-component redirect 会造成 `/setup → /setup` 死循环）。
 */

import { expect, test } from '@playwright/test';

import { fulfilJson, mockApi } from './fixtures';

const freshSetupState = {
  status: 200,
  body: {
    required: true,
    active_profile: null,
    profiles: [],
    gates: { g1: 'degraded', g2: 'ok', g3: 'ok' },
    kernel: { mode: 'template', reason: 'offline e2e', core_version: null },
  },
};

test('未配置时访问课程页会被送到 /setup，并带回跳地址', async ({ page }) => {
  await mockApi(page, { 'GET /api/setup/state': freshSetupState } satisfies Record<string, unknown>);
  await page.goto('/course/cv_demo01/overview');
  await expect(page).toHaveURL(/\/setup\?next=/);
  await expect(page.getByRole('heading', { name: '配置 AI 服务' })).toBeVisible();
});

test('后端不可达时 /setup 显示"后端未就绪"而不是重定向', async ({ page }) => {
  await page.route('**/api/setup/state', async (route) => {
    await fulfilJson(
      route,
      {
        error: {
          code: 'API_UNREACHABLE',
          message: '后端服务未启动或无法连接。',
          hint: '运行 .\\start.ps1 启动三进程。',
          retryable: true,
          req_id: 'web-test',
        },
      },
      503,
    );
  });
  await page.goto('/setup');
  // Next 自己也会挂一个 `role="alert"` 的路由播报器，必须按内容过滤
  await expect(page.locator('[role="alert"]', { hasText: '后端未就绪' })).toBeVisible();
  await expect(page).toHaveURL(/\/setup/);
});
