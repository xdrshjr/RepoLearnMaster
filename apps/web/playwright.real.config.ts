/**
 * 真链路 E2E 配置（hardening spec §3.2.3，L5 层）。
 *
 * 与 `playwright.config.ts`（离线层）的三处关键差异：
 *
 * 1. **没有 `webServer`**：fake GitHub / FastAPI / Next 三进程由
 *    `scripts/e2e-real.mjs` 起停。Playwright 的 `webServer` 生命周期只覆盖
 *    测试进程本身，既管不了另外两个进程，也没法和 `taskkill /T /F` 的子树清理
 *    对齐（两套清理逻辑打架的结果是端口留到下轮，下一轮第 2 步直接失败）。
 * 2. **串行**：`workers: 1` + `fullyParallel: false`。四条用例共享**同一个** SQLite
 *    与同一个对象目录，并行跑会让"课程生成中"和"课程已就绪"在两个 worker 之间
 *    互相打断——那是测试自身制造的失败，不是产品的。
 * 3. **超时更长**：template runtime 的真生成链路（拉 tarball → 解包 → 静态分析 →
 *    写 12 课时 → 发布）比离线层的手写夹具慢一个数量级；`expect` 给 30s 是因为
 *    准备页的 SSE 节点推进与书籍轮询都是秒级粒度。
 *
 * 地址全部来自编排器注入的环境变量（默认值只是为了能单独手跑一条用例）。
 */

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e-real',
  fullyParallel: false, // 共享一个 DB，串行
  forbidOnly: Boolean(process.env.CI),
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000, // 真生成链路（template runtime）比离线层慢
  expect: { timeout: 30_000 },
  use: {
    baseURL: process.env.E2E_WEB_URL ?? 'http://127.0.0.1:3100',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  },
  projects: [{ name: 'chromium-real', use: { ...devices['Desktop Chrome'] } }],
  // 注意：不配置 webServer —— 三进程由 scripts/e2e-real.mjs 管，
  // 否则 Playwright 的 webServer 生命周期与我们的清理逻辑会打架。
});
