/**
 * T-E2E-R3 · 生成书籍 → 阅读器 → PDF 入口（hardening spec §3.2.3 表第 3 行）。
 *
 * 两条断言，第二条是本层的**重点**：
 *
 * ① `POST` 建书 → Job → 阅读器正文非空且章节数 ≥ 1；
 * ② PDF 入口必须与 `/healthz.gates` 的 **`g2`**（chromium）一致，而且**先断言
 *    `g2 !== "unknown"`**——读到 `unknown` 直接判失败。否则这条断言会靠"什么都
 *    不知道"蒙过去：`unknown` 既不是"有"也不是"没有"，任何一侧都能被它凑出来。
 *
 * 两个分支都断言，没有"有就断言、无就跳过"：
 * * `g2 === 'ok'`      → 导出引擎必须是 `chromium`，页面出现「下载 PDF」，且
 *                       `pdf_url` 的 `content-type` 是 `application/pdf`；
 * * `g2 === 'missing'` → 导出引擎必须降级成 `browser-print`，页面出现「打开打印
 *                       视图」，且**不出现**可点的「下载 PDF」（假 PDF 比没有 PDF 更糟）。
 *
 * ## 端点的实际形状（与 spec §3.2.3 表的字面写法不同，以仓库为准）
 *
 * 表里写的是 `POST /api/books`，但仓库里建书是
 * `POST /v1/courses/{course_id}/books`（`apps/api/repolearn/routers/books.py`），
 * 经 BFF 就是 `POST /api/courses/{id}/books`；`/api/books/*` 只覆盖
 * `/v1/books/*`（详情、章节、PDF）。这里按仓库实现走，未改动产品。
 */

import {
  bypassSetup,
  expect,
  getJson,
  postJson,
  test,
  waitForJob,
  type BookDetail,
  type PdfStatus,
} from './fixtures';

interface HealthResponse {
  ok: boolean;
  gates?: Record<string, string>;
}

interface BookCreated {
  book_id?: string;
  job_id?: string | null;
  reused?: boolean;
}

interface BookChapterDetail {
  key: string;
  title: string;
  blocks: Array<{ type: string; text?: string }>;
}

interface PdfCreated {
  job_id?: string;
}

test('T-E2E-R3 书籍生成 + PDF 入口与 Gate 0 的 g2 一致', async ({ page, context, seededCourse }, testInfo) => {
  test.setTimeout(180_000);
  await bypassSetup(context);

  // ---- ② 的前提：g2 必须是**确定结论** ---------------------------------------
  const health = await getJson<HealthResponse>(page, '/api/healthz');
  const g2 = health.gates?.['g2'];
  expect(
    g2,
    'gates.g2 根本不在 /healthz 响应里：说明 REPOLEARN_RUN_DIR 指错了，或第 5.5 步没跑',
  ).toBeTruthy();
  expect(
    g2,
    `gates.g2=${g2}：读不到 Chromium 的探测结论（preflight.json 缺失/损坏）。` +
      '这指向编排器第 5.5 步没跑，而不是 PDF 功能坏了——先修环境，别改断言',
  ).not.toBe('unknown');

  await page.goto('/');

  // ---- ① 建书 → Job → 阅读器 ------------------------------------------------
  const created = await postJson<BookCreated>(page, `/api/courses/${encodeURIComponent(seededCourse.id)}/books`, {
    preset: 'standard',
    include_audio: false,
  });
  // 200 + reused 是合法的缓存命中（同一轮重跑时会出现），其余必须是 202。
  expect([200, 202], `POST /api/courses/{id}/books 返回 ${created.status}：${JSON.stringify(created.body)}`).toContain(
    created.status,
  );
  const bookId = created.body.book_id;
  expect(bookId, '建书响应必须带 book_id').toBeTruthy();

  if (created.body.job_id) {
    const job = await waitForJob(page, created.body.job_id, testInfo);
    expect(['ready', 'partial'], `书籍任务失败：${JSON.stringify(job.error ?? {})}`).toContain(job.status);
  }

  // 书籍状态（reused 分支没有 job，直接轮询详情）。
  await expect
    .poll(
      async () => (await getJson<BookDetail>(page, `/api/books/${encodeURIComponent(bookId as string)}`)).status,
      { timeout: 60_000, message: '书籍必须从 generating 走到 ready' },
    )
    .toBe('ready');

  const book = await getJson<BookDetail>(page, `/api/books/${encodeURIComponent(bookId as string)}`);
  expect(book.chapters.length, '书籍章节数必须 ≥ 1').toBeGreaterThanOrEqual(1);

  await page.goto(`/book/${encodeURIComponent(bookId as string)}`);
  const article = page.locator('article').first();
  await expect(article, '阅读器必须渲染出章节正文').toBeVisible({ timeout: 30_000 });
  const readerText = (await article.innerText()).trim();
  expect(readerText.length, '阅读器正文不能为空').toBeGreaterThan(0);
  await expect(article.getByRole('heading', { level: 1 })).toContainText(book.chapters[0]?.title ?? '');

  const firstChapter = await getJson<BookChapterDetail>(
    page,
    `/api/books/${encodeURIComponent(bookId as string)}/chapters/${encodeURIComponent(book.chapters[0]?.key ?? '')}`,
  );
  const chapterText = firstChapter.blocks.map((block) => String(block.text ?? '')).join('').trim();
  expect(chapterText.length, '第一章的 blocks 必须带正文（不能只有标题）').toBeGreaterThan(0);

  // ---- ② PDF 入口与 g2 对齐 --------------------------------------------------
  //
  // 为什么用 API 起导出、而不是点页面上的「生成 PDF」按钮：
  // `book_service.pdf_status()` 在**没有任何导出记录**时返回
  // `PdfStatus(status="queued", engine=settings.pdf_default_engine)`，而
  // `PdfPreview` 把 `queued` 当 pending → 按钮被 `disabled={pending}` 永久禁用、
  // 文案停在"生成中…"。也就是说"新书的 PDF 页面永远起不了导出"是产品侧的一个
  // 真实缺陷（不在本节点的文件范围内）。这里按 spec 的断言口径（PDF **入口**与
  // g2 一致）用 API 建导出，再把页面状态当作被测对象；缺陷已写进报告。
  const pdfCreate = await postJson<PdfCreated>(page, `/api/books/${encodeURIComponent(bookId as string)}/pdf`, {
    engine: 'chromium',
  });
  expect(pdfCreate.status, 'POST /api/books/{id}/pdf 必须 202（排队一个导出任务）').toBe(202);
  expect(pdfCreate.body.job_id, 'PDF 导出必须返回 job_id').toBeTruthy();

  // 导出是一个 Job：等 status 落到终态（browser-print 会立刻降级，chromium 要几十秒）。
  await expect
    .poll(
      async () =>
        (await getJson<PdfStatus>(page, `/api/books/${encodeURIComponent(bookId as string)}/pdf`)).status,
      { timeout: 120_000, message: 'PDF 导出必须离开 queued/running 状态' },
    )
    .toMatch(/^(ready|failed)$/);

  const pdf = await getJson<PdfStatus>(page, `/api/books/${encodeURIComponent(bookId as string)}/pdf`);
  await testInfo.attach('pdf-status.json', { body: JSON.stringify(pdf, null, 2), contentType: 'application/json' });

  // 页面重新加载后按 g2 分支断言（页面自己会 refetch 到刚生成的这条导出记录）。
  await page.goto(`/book/${encodeURIComponent(bookId as string)}/pdf`);

  if (g2 === 'ok') {
    // 有 Chromium：必须真的产出 PDF 字节。
    expect(
      pdf.engine,
      `gates.g2=ok（probe_gates 调用的是**产品自己的判据** rendering/pdf.py::chromium_available()），` +
        `但导出引擎是 ${pdf.engine}。两个判据已同源，所以这只可能是"同一台机器、同一份浏览器，` +
        '在 API 进程的事件循环里却起不来"——即 sync playwright API 被当成了 async 用法（R16 的真病因）。' +
        '先去 api.log 找 pdf_render_failed，不要在这里放宽断言。',
    ).toBe('chromium');
    expect(pdf.pdf_url, 'g2=ok 时必须给出可下载的 pdf_url').toBeTruthy();

    await expect(page.getByRole('link', { name: /下载 PDF/ }), 'g2=ok 时页面必须提供「下载 PDF」').toBeVisible({
      timeout: 60_000,
    });
    await expect(page.getByRole('link', { name: /打开打印视图/ })).toHaveCount(0);

    // 下载地址必须真的吐出 PDF（不是 HTML 错误页、不是 0 字节）。
    const download = await page.request.get(pdf.pdf_url as string);
    expect(download.status(), 'pdf_url 必须可下载').toBe(200);
    expect(download.headers()['content-type'] ?? '', 'pdf_url 必须回 application/pdf').toContain(
      'application/pdf',
    );
    const body = await download.body();
    expect(body.length, 'PDF 不能是 0 字节').toBeGreaterThan(0);
  } else {
    // 无 Chromium：必须显示打印视图入口，且**不能**有假的可点下载。
    expect(
      pdf.engine,
      `gates.g2=${g2}（没有可用 chromium），但导出引擎是 ${pdf.engine}——降级没有生效`,
    ).toBe('browser-print');
    expect(pdf.print_view_url, 'g2 缺失时必须给出打印视图地址').toBeTruthy();

    await expect(
      page.getByRole('link', { name: /打开打印视图/ }),
      'g2 缺失时页面必须给出「打开打印视图」入口',
    ).toBeVisible({ timeout: 60_000 });
    await expect(
      page.getByRole('link', { name: /下载 PDF/ }),
      'g2 缺失时**不许**出现可点的「下载 PDF」（后端根本没有生成字节）',
    ).toHaveCount(0);
  }
});
