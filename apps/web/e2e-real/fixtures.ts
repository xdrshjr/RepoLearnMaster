/**
 * 真链路 E2E 的共用能力（hardening spec §3.2.3）。
 *
 * 这一层与 `e2e/fixtures.ts`（离线层）的方向相反：离线层**伪造**整个 `/api/*`，
 * 这一层一行都不伪造——所有请求都真的打到 `scripts/e2e-real.mjs` 起的三进程上。
 * 因此这里只需要三件"定位用"的工具，而不是一堆 mock 数据：
 *
 * * `seededCourse` —— 直接问 API 拿 `seed-demo` 那门课的 id（**不走 UI**：
 *   把"导入"与"读课"两条链路的失败混在一起，红了之后要先猜是哪条断的）；
 * * `bypassSetup`  —— 首启守卫（`rl_setup` cookie）已有离线层用例覆盖，
 *   真链路层不该被它拦在 `/setup`；
 * * `waitForJob`   —— 轮询 `GET /api/jobs/{id}` 到终态，失败时把 `error` 与课程的
 *   `warnings` 打进 `testInfo.attach`（否则 CI 面板上只剩一句"超时"）。
 *
 * 顺便说明两处**故意**存在的细节，它们都是"为什么不在别处做"的答案：
 *
 * 1. `postJson` 走 `page.evaluate(fetch)` 而不是 `request.post`：写操作要 CSRF
 *    双提交（cookie `rl_csrf` + 头 `X-CSRF-Token`），而 cookie 由浏览器持有。
 *    在页面里发请求最贴近真实浏览器，也不用在测试里复刻一份 cookie jar 逻辑。
 * 2. `deleteCoursesForRepo` 只为 CI 的 `retries: 1` 服务：同一 commit 第二次
 *    `POST /courses` 会命中内容缓存返回 200 `reused`，那样"必须 202"这条断言
 *    会被**重跑本身**破坏。软删除后再导入仍会拿到 202（后端"复活"分支）。
 */

import { test as base, expect, type BrowserContext, type Page, type TestInfo } from '@playwright/test';

/** `seed-demo` 固定的仓库名（见 `apps/api/repolearn/cli.py`）。 */
export const DEMO_REPO_FULL_NAME = 'microsoft/autogen (demo)';
export const DEMO_COURSE_TITLE = 'AutoGen 带读：Agent 如何对话';

/** 任务终态（`ready` / `partial` 属于"能用"，`failed` 属于"必须报错"）。 */
const TERMINAL_STATUSES = new Set(['ready', 'partial', 'failed']);

export interface SeededCourse {
  id: string;
  title: string;
  fullName: string;
  lessonCount: number;
}

export interface CourseListItem {
  id: string;
  title: string;
  lesson_count?: number;
  status?: string;
  repo: { full_name: string };
}

export interface CourseListResponse {
  items: CourseListItem[];
  next_cursor?: string | null;
  mode?: string;
  fallback_reason?: string | null;
  next_offset?: number | null;
  total?: number | null;
}

export interface CourseDetail {
  id: string;
  title: string;
  status: string;
  lesson_count: number;
  repo: { full_name: string; html_url?: string };
  sections: Array<{ key: string; title: string; lessons: Array<{ key: string; title: string }> }>;
  warnings?: unknown[];
}

export interface JobDetail {
  id: string;
  kind: string;
  status: string;
  progress?: number;
  node?: string | null;
  message?: string | null;
  course_id?: string | null;
  book_id?: string | null;
  error?: Record<string, unknown> | null;
}

export interface BookDetail {
  id: string;
  course_version_id: string;
  status: string;
  title: string;
  chapters: Array<{ key: string; title: string; words?: number }>;
  word_count: number;
}

export interface BookChapterDetail {
  key: string;
  title: string;
  blocks: Array<{ type: string; text?: string }>;
}

export interface PdfStatus {
  status: string;
  pdf_url?: string | null;
  engine: string;
  print_view_url?: string | null;
  pages?: number;
  bytes?: number;
  error?: Record<string, unknown>;
}

/**
 * 首启守卫的绕过。
 *
 * `domain` 从真实 baseURL 推出来（而不是写死 127.0.0.1）：编排器允许
 * `E2E_WEB_PORT` 覆盖端口，手跑时也可能是 `localhost`——cookie 域对不上时
 * 表现是"每个用例都跳 /setup"，那种红会浪费半小时。
 */
export async function bypassSetup(context: BrowserContext, baseURL?: string): Promise<void> {
  const origin = baseURL ?? process.env.E2E_WEB_URL ?? 'http://127.0.0.1:3100';
  const domain = new URL(origin).hostname;
  await context.addCookies([{ name: 'rl_setup', value: '1', domain, path: '/' }]);
}

/** 一次 API 读取（GET 没有 CSRF 约束，直接借浏览器上下文的 cookie）。 */
export async function getJson<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(path, { headers: { accept: 'application/json' } });
  expect(response.status(), `GET ${path} 应当 200`).toBe(200);
  return (await response.json()) as T;
}

/**
 * 在**页面里**发一个写请求，照抄 `lib/api/client.ts` 的双提交 CSRF。
 *
 * 返回真实状态码：四条用例里有多处断言就是"状态码必须是 202"，所以不能让
 * 封装把 202/200 抹平成"成功"。
 */
export async function postJson<T>(
  page: Page,
  path: string,
  body: unknown,
): Promise<{ status: number; body: T }> {
  return page.evaluate(
    async ({ path: target, payload }) => {
      const token =
        document.cookie
          .split('; ')
          .find((item) => item.startsWith('rl_csrf='))
          ?.slice('rl_csrf='.length) ?? '';
      const response = await fetch(target, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-csrf-token': decodeURIComponent(token) },
        body: JSON.stringify(payload),
        credentials: 'same-origin',
      });
      let parsed: unknown = null;
      try {
        parsed = await response.json();
      } catch {
        parsed = null;
      }
      return { status: response.status, body: parsed as T };
    },
    { path, payload: body },
  );
}

/** 列出全部课程（`/api/courses` 会转发到 `/v1/courses`）。 */
export async function listCourses(page: Page, query = 'limit=50'): Promise<CourseListResponse> {
  return getJson<CourseListResponse>(page, `/api/courses?${query}`);
}

/**
 * 把某个仓库名下的课程全部软删除（只为"同一轮重跑仍然拿到 202"服务）。
 *
 * 用 `page.evaluate` 而不是 `request.delete`：DELETE 同样是写操作、同样要 CSRF。
 * 失败不抛：删不掉时后面的断言会自己说出真相，而不是让清理步骤抢戏。
 */
export async function deleteCoursesForRepo(page: Page, fullName: string): Promise<number> {
  const courses = await listCourses(page);
  const targets = courses.items.filter((item) => item.repo.full_name === fullName);
  let removed = 0;
  for (const course of targets) {
    const status = await page.evaluate(async (id) => {
      const token =
        document.cookie
          .split('; ')
          .find((item) => item.startsWith('rl_csrf='))
          ?.slice('rl_csrf='.length) ?? '';
      const response = await fetch(`/api/courses/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        headers: { 'x-csrf-token': decodeURIComponent(token) },
        credentials: 'same-origin',
      });
      return response.status;
    }, course.id);
    if (status === 204) removed += 1;
  }
  return removed;
}

/**
 * 轮询 `GET /api/jobs/{id}` 到终态。
 *
 * 失败（`status === 'failed'`）时不抛"超时"了事：把 `error` 与课程 `warnings`
 * **附到报告里**，CI 面板上直接能看到错误码（例如 `EMPTY_MIRROR`）。
 * 注意 `JobDetail` 本身没有 `warnings` 字段——warnings 挂在课程上（spec §3.2.6）。
 */
export async function waitForJob(
  page: Page,
  jobId: string,
  testInfo?: TestInfo,
  timeoutMs = 90_000,
): Promise<JobDetail> {
  const deadline = Date.now() + timeoutMs;
  let last: JobDetail | null = null;
  while (Date.now() < deadline) {
    const response = await page.request.get(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (response.status() === 200) {
      last = (await response.json()) as JobDetail;
      if (TERMINAL_STATUSES.has(last.status)) {
        if (last.status === 'failed') {
          await attachFailureContext(page, last, testInfo);
        }
        return last;
      }
    }
    await page.waitForTimeout(500);
  }
  await attachFailureContext(page, last, testInfo);
  const status = last?.status;
  if (!status || !TERMINAL_STATUSES.has(status)) {
    throw new Error(`任务 ${jobId} 在 ${timeoutMs}ms 内没有进入终态（最后状态：${status ?? '无响应'}）`);
  }
  return last as JobDetail;
}

async function attachFailureContext(
  page: Page,
  job: JobDetail | null,
  testInfo?: TestInfo,
): Promise<void> {
  if (!testInfo) return;
  const parts: string[] = [];
  parts.push(`job: ${JSON.stringify(job, null, 2)}`);
  if (job?.course_id) {
    try {
      const course = await getJson<CourseDetail>(page, `/api/courses/${encodeURIComponent(job.course_id)}`);
      parts.push(`course.warnings: ${JSON.stringify(course.warnings ?? [], null, 2)}`);
    } catch (error) {
      parts.push(`course.warnings: (读取失败 ${error instanceof Error ? error.message : String(error)})`);
    }
  }
  await testInfo.attach('job-failure.json', {
    body: parts.join('\n\n'),
    contentType: 'application/json',
  });
}

/** 找 `seed-demo` 那门课。找不到就明确报"第 5 步没跑"，而不是一句超时。 */
async function findSeededCourse(page: Page): Promise<SeededCourse> {
  const payload = await listCourses(page, 'limit=50');
  const match = payload.items.find((item) => item.repo.full_name === DEMO_REPO_FULL_NAME);
  expect(
    match,
    `找不到 ${DEMO_REPO_FULL_NAME}：编排器第 5 步的 seed-demo 没跑成（不要在本层修夹具课程，它每次运行都会被重建）`,
  ).toBeTruthy();
  const course = match as CourseListItem;
  return {
    id: course.id,
    title: course.title,
    fullName: course.repo.full_name,
    lessonCount: course.lesson_count ?? 0,
  };
}

/**
 * `test` 是离线层 `test` 的超集：多一个 `seededCourse` fixture。
 *
 * 为什么用 fixture 而不是 `beforeEach`：每条用例都可能不需要它（例如
 * `search-parity` 只读列表），fixture 的惰性正合适；而且失败信息会落在
 * "准备数据"这一步，不会和断言混在一起。
 */
export const test = base.extend<{ seededCourse: SeededCourse }>({
  seededCourse: async ({ page }, use) => {
    const course = await findSeededCourse(page);
    await use(course);
  },
});

export { expect };
