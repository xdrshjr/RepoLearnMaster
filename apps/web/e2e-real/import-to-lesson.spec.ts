/**
 * T-E2E-R1 · 导入 → Job → 准备页 SSE → 工作台 → 首步播放（hardening spec §3.2.3 表第 1 行）。
 *
 * 这条用例是整条主链路的"体检"：它跑的不是夹具，而是**真的** FastAPI + 真的
 * 假 GitHub + 真的 Next BFF。因此每一条断言都写成"会失败的断言"：
 *
 * ① 粘贴地址后**必须** 202 并跳到准备页（200 只表示命中缓存，那说明这一轮根本没生成）；
 * ② SSE 至少收到 3 个不同 `node` 的进度事件（证明 BFF 逐 chunk 透传，不是最后一坨）；
 * ③ 完成后 `/course/<id>/overview` 出现课时标题；
 * ④ 播放器时间轴 `steps ≥ 1` 且首步 `durationMs > 0`。
 *
 * ## 关于"粘贴哪个地址"（与 spec 的一处有意偏离，必须记录）
 *
 * spec §3.2.3 写的是粘贴 `http://127.0.0.1:<fake>/microsoft/autogen`。但当前前端
 * 的 `apps/web/src/lib/repo/parseRepoUrl.ts` 把 host 硬编码成 `github.com`，
 * 这个地址会在**前端**就被拒（"目前只支持 github.com 的公开仓库"），请求根本
 * 发不出去——即 spec 的 ① 在今天的仓库上无法通过 UI 验证。
 *
 * 因此这里的做法是：粘贴 `https://github.com/microsoft/autogen`（前端接受），
 * 而**后端**因为 `REPOLEARN_GITHUB_API_BASE/WEB_BASE` 指向假端点，整条链路的
 * 出站流量仍然全部打到假 GitHub。为了证明"打的确实是假端点"，用例额外断言
 * `repo.html_url === <fake>/microsoft/autogen`（这个值只能由配置的 web base 产生）。
 * 被前端挡住的那条路径单独留成 `test.fixme`，不写成恒真断言。
 */

import {
  bypassSetup,
  deleteCoursesForRepo,
  expect,
  getJson,
  listCourses,
  test,
  waitForJob,
  type CourseDetail,
} from './fixtures';

/** 编排器注入的假 GitHub 地址（与 REPOLEARN_GITHUB_WEB_BASE 同源）。 */
const FAKE_GH_URL = (process.env.E2E_FAKE_GH_URL ?? 'http://127.0.0.1:9911').replace(/\/+$/, '');
const REPO_INPUT = 'https://github.com/microsoft/autogen';
const REPO_FULL_NAME = 'microsoft/autogen';

interface SseFrame {
  type: string;
  node: string | null;
  status: string | null;
  seq: number;
}

interface SseCapture {
  status: number;
  contentType: string | null;
  cacheControl: string | null;
  xAccelBuffering: string | null;
  contentLength: string | null;
  /** `reader.read()` 拿到数据的次数：缓冲型的中间层会把整段流压成 1 次。 */
  reads: number;
  frames: SseFrame[];
  firstFrameAtMs: number | null;
  endedAtMs: number;
}

interface PlaybackBundleLike {
  steps: Array<{
    index: number;
    title: string;
    duration_ms: number;
    segments: Array<{ id: string; text: string }>;
  }>;
  lesson: { key: string; title: string };
}

test('T-E2E-R1 导入 → Job → 准备页 SSE → 工作台 → 首步播放', async ({ page, context }, testInfo) => {
  test.setTimeout(150_000);
  await bypassSetup(context);

  // 同一轮里的重跑（CI `retries: 1`）会命中内容缓存返回 200 `reused`，那样"必须 202"
  // 就被重跑本身破坏了。软删除后重新导入仍会走 202（后端有"复活"分支）。
  await page.goto('/');
  await deleteCoursesForRepo(page, REPO_FULL_NAME);

  // 预热准备页：`next dev` 首次访问某条路由要现编译（几秒到十几秒），
  // 编译期会把 SSE 的直播窗口整段吃掉——那是测试自己制造的假失败。
  await page.goto('/repo/microsoft/autogen');
  await page.goto('/');

  // ---- ① 粘贴 → 202 → 准备页 ------------------------------------------------
  await page.getByLabel('GitHub 仓库地址').fill(REPO_INPUT);
  await expect(page.getByText(`已解析：${REPO_FULL_NAME}`)).toBeVisible();

  const postResponse = page.waitForResponse(
    (response) => response.url().includes('/api/courses') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '生成学习课程' }).click();
  const created = await postResponse;
  expect(
    created.status(),
    'POST /api/courses 必须是 202（新建 Job）；200 只表示命中已有课程，说明这一轮没有真的生成',
  ).toBe(202);

  const createdBody = (await created.json()) as { job_id?: string; course_id?: string; reused?: boolean };
  const jobId = createdBody.job_id;
  expect(jobId, '202 响应必须带 job_id').toBeTruthy();
  expect(createdBody.reused ?? false, '202 不应该是"复用"').toBe(false);

  await page.waitForURL(
    (url) => url.pathname === '/repo/microsoft/autogen' && url.searchParams.get('job') === jobId,
    { timeout: 30_000 },
  );
  await expect(page.getByRole('heading', { name: REPO_FULL_NAME })).toBeVisible();

  // ---- ② SSE：逐 chunk 透传 + 至少 3 个不同 node ---------------------------------
  const sse = await page.evaluate(async (id: string): Promise<SseCapture> => {
    const response = await fetch(`/api/sse/jobs/${encodeURIComponent(id)}`, {
      headers: { accept: 'text/event-stream' },
      cache: 'no-store',
      credentials: 'same-origin',
    });
    const headers = {
      contentType: response.headers.get('content-type'),
      cacheControl: response.headers.get('cache-control'),
      xAccelBuffering: response.headers.get('x-accel-buffering'),
      contentLength: response.headers.get('content-length'),
    };
    const reader = response.body?.getReader();
    const frames: SseFrame[] = [];
    let reads = 0;
    let firstFrameAtMs: number | null = null;
    let buffer = '';
    const decoder = new TextDecoder();
    if (reader) {
      for (;;) {
        const { done, value } = await reader.read();
        if (value && value.length > 0) {
          reads += 1;
          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split('\n\n');
          buffer = blocks.pop() ?? '';
          for (const block of blocks) {
            const eventLine = block.split('\n').find((line) => line.startsWith('event: '));
            const dataLine = block.split('\n').find((line) => line.startsWith('data: '));
            if (!dataLine) continue;
            let parsed: Record<string, unknown> | null = null;
            try {
              parsed = JSON.parse(dataLine.slice('data: '.length)) as Record<string, unknown>;
            } catch {
              parsed = null;
            }
            const data = (parsed?.data ?? {}) as Record<string, unknown>;
            if (firstFrameAtMs === null) firstFrameAtMs = performance.now();
            frames.push({
              type: String(parsed?.type ?? eventLine?.slice('event: '.length) ?? 'unknown'),
              node: typeof data.node === 'string' ? data.node : null,
              status: typeof data.status === 'string' ? data.status : null,
              seq: Number(parsed?.seq ?? 0),
            });
          }
        }
        if (done) break;
      }
    }
    return { status: response.status, ...headers, reads, frames, firstFrameAtMs, endedAtMs: performance.now() };
  }, jobId as string);

  await testInfo.attach('sse-capture.json', {
    body: JSON.stringify(sse, null, 2),
    contentType: 'application/json',
  });

  expect(sse.status, 'SSE 端点必须 200').toBe(200);
  // §3.2.5 的"不是最后一坨"落在响应头上：任何重压缩/缓冲都会把这三条抹掉。
  expect(sse.contentType ?? '', 'SSE 必须声明 text/event-stream').toContain('text/event-stream');
  expect(sse.cacheControl ?? '', 'BFF 必须回 no-transform').toContain('no-transform');
  expect(sse.xAccelBuffering ?? '', 'BFF 必须回 X-Accel-Buffering: no').toBe('no');

  const nodes = [...new Set(sse.frames.map((frame) => frame.node).filter((node): node is string => Boolean(node)))];
  expect(
    nodes.length,
    `SSE 只收到 ${nodes.length} 个不同 node 的进度事件（${nodes.join(', ') || '无'}）：` +
      '至少要有 3 个，否则说明进度是最后一次性给的，或者事件流被中间层缓冲了',
  ).toBeGreaterThanOrEqual(3);

  const terminal = sse.frames.find((frame) => frame.type === 'job.completed');
  expect(terminal, 'SSE 必须收到 job.completed（服务端主动关流，§3.2.5）').toBeTruthy();
  expect(['ready', 'partial'], '生成终态必须是 ready 或 partial').toContain(terminal?.status);

  // ---- Job 终态 + 假端点确实被用到 -------------------------------------------
  const job = await waitForJob(page, jobId as string, testInfo);
  expect(['ready', 'partial'], `生成失败：${JSON.stringify(job.error ?? {})}`).toContain(job.status);

  const list = await listCourses(page, `q=${encodeURIComponent(REPO_FULL_NAME)}&limit=50`);
  const course = list.items.find((item) => item.repo.full_name === REPO_FULL_NAME);
  expect(course, `${REPO_FULL_NAME} 应该在课程列表里（生成完成后）`).toBeTruthy();
  const courseId = (course as { id: string }).id;

  const detail = await getJson<CourseDetail>(page, `/api/courses/${encodeURIComponent(courseId)}`);
  // 证明出站流量打的是假端点：这个值只能由 REPOLEARN_GITHUB_WEB_BASE 产生。
  expect(
    detail.repo.html_url ?? '',
    `repo.html_url 应当是配置的 GitHub web base（${FAKE_GH_URL}）拼装值，说明这一轮打的是假端点而不是真的 github.com`,
  ).toBe(`${FAKE_GH_URL}/${REPO_FULL_NAME}`);

  const firstLesson = detail.sections.flatMap((section) => section.lessons)[0];
  expect(firstLesson, '生成出的课程必须至少有一个课时').toBeTruthy();

  // ---- ③ 工作台出现课时标题 ---------------------------------------------------
  await page.goto(`/course/${encodeURIComponent(courseId)}/overview`);
  await expect(page.getByRole('heading', { name: detail.title })).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByText(firstLesson?.title ?? '从未出现的课时标题').first(),
    '课时标题必须出现在工作台里（大纲或播放器头部）',
  ).toBeVisible();

  // ---- ④ 播放器时间轴 --------------------------------------------------------
  const playback = await getJson<PlaybackBundleLike>(
    page,
    `/api/courses/${encodeURIComponent(courseId)}/lessons/${encodeURIComponent(firstLesson?.key ?? '1.1')}/playback`,
  );
  expect(playback.steps.length, '播放器的 steps 必须 ≥ 1').toBeGreaterThanOrEqual(1);
  expect(playback.steps[0]?.duration_ms ?? 0, '首步 durationMs 必须 > 0').toBeGreaterThan(0);

  // UI 侧再验一次：播放器真的把这份 bundle 变成了时间轴。
  const counter = page.getByText(/^1\/\d+$/).first();
  await expect(counter, '播放器必须渲染"1/N"的步骤计数（说明时间轴非空）').toBeVisible();
  const stepCount = Number((await counter.innerText()).trim().split('/')[1]);
  expect(stepCount, '播放器时间轴的步数必须与后端 bundle 一致').toBe(playback.steps.length);

  const scrubber = page.getByLabel('当前步骤进度');
  const maxAttr = await scrubber.getAttribute('max');
  expect(Number(maxAttr), '首步进度条的 max 必须是真实时长（durationMs > 0）').toBe(
    playback.steps[0]?.duration_ms,
  );
  expect(Number(maxAttr), '首步时长必须大于 0').toBeGreaterThan(0);
});

/**
 * spec §3.2.3 ① 的"配置端点地址也能粘贴"，当前**跑不通**，故标 fixme。
 *
 * TODO(前端层)：`apps/web/src/lib/repo/parseRepoUrl.ts` 里
 * `if (!/(^|\.)github\.com$/i.test(url.hostname)) return { ok:false, error:'目前只支持 github.com 的公开仓库' }`
 * 把允许域硬编码了。后端 `parse_repo_url` 已按 `REPOLEARN_GITHUB_WEB_BASE` 放行
 * （spec §3.2.1 / §4.1 第 2 行），缺口只在前端。修好后删掉 `.fixme` 即可，
 * 断言与上面那条完全一致（202 + 跳准备页）。
 */
test.fixme('T-E2E-R1 粘贴配置端点地址（http://127.0.0.1:<fake>/microsoft/autogen）也必须 202', async ({
  page,
  context,
}) => {
  await bypassSetup(context);
  await page.goto('/');
  await page.getByLabel('GitHub 仓库地址').fill(`${FAKE_GH_URL}/${REPO_FULL_NAME}`);
  await expect(page.getByText(`已解析：${REPO_FULL_NAME}`)).toBeVisible();
  const postResponse = page.waitForResponse(
    (response) => response.url().includes('/api/courses') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '生成学习课程' }).click();
  expect((await postResponse).status(), '配置端点地址必须被接受并返回 202').toBe(202);
});
