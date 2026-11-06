/**
 * Playwright 配置（spec §8.3 的两层策略）。
 *
 * 默认这一跑就是**离线层**：`page.route` 顶替全部 `/api/*`，不启动 API、不装
 * 数据库、不需要 API Key，因此它能在任何机器与 CI 上稳定复现（< 3 分钟）。
 *
 * 只要一个能跑 Next 的进程：优先复用已在跑的 `:3000`（开发时 `start.ps1` 已经
 * 起好了），没有就自己 `next dev` 起来。
 */

import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.REPOLEARN_WEB_PORT ?? 3000);
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  timeout: 30_000,
  // `next dev` 首次访问某个路由要现编译（几秒到十几秒）。8s 在并行跑新路由时
  // 会随机超时，把门禁变成噪声。15s 仍然远小于 30s 的用例上限。
  expect: { timeout: 15_000 },
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npx next dev --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 120_000,
    env: {
      // 不要在生产模式下跑 `next dev`：middleware 的 edge 沙箱会拒绝 eval，
      // 表现为每个页面 500（docs/runbook.md 的排查表里也记了这一条）。
      NODE_ENV: 'development',
      REPOLEARN_API_BASE: 'http://127.0.0.1:8000',
    },
  },
});
