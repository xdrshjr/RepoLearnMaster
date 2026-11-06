/**
 * T-E2E-R2 · 答题 → 解释 + evidence → 重放幂等 → 完课页（hardening spec §3.2.3 表第 2 行）。
 *
 * 三条断言（都是"会失败"的）：
 * ① 选中答案后出现解释与"证据"链接，点进后跳到工作台且 `?file=`/`?line=` **生效**
 *    （不是"URL 里有参数"就算过——必须看到 app 真的去读了那个文件的源码）；
 * ② 同题二次提交返回 `replayed=true` 且**不重复计数**（真后端的幂等键）；
 * ③ 完课页的 `percent` 与已学课时数一致。
 *
 * ## 关于 ③ 的判定口径（必须写清楚，否则它容易退化成恒真）
 *
 * 这一轮我在播放器里**真的**把 4 个课时都看到了末尾（`status === 'ended'` 时前端
 * 会 PUT 一次 `/progress`），所以"已学课时数 = 4 / 总数 4"，完课页应当显示 100%。
 * 断言把 `percent` 与 `round(100 × 已学 / 总数)` 对齐，并且**同时**要求
 * `completed === true`。
 *
 * 已知偏差（不在本轮修复范围内，报告里另列）：`PlayerProvider.persist()` 里
 * `percent = (stepIndex + stepPercent) / steps.length` 是**课时内**进度，而它被写进了
 * `user_progress.percent`（课程级字段）。因此"只学了一节课"时 percent 就已经是 100，
 * 「percent 与已学课时数一致」只在"全部学完"这一端成立。把断言写成 1/4 → 25 会
 * 立刻变红，那是产品侧要改的语义，不是本层可以绕过的。
 */

import type { Page } from '@playwright/test';

import {
  bypassSetup,
  expect,
  getJson,
  test,
  type CourseDetail,
} from './fixtures';

interface RecapResponse {
  percent: number;
  completed: boolean;
  quiz_stats: Record<string, unknown>;
  knowledge_points: unknown[];
}

interface QuizAnswerResponse {
  correct: boolean;
  explanation_md: string;
  evidence: Array<{ file: string; line_start: number; line_end: number }>;
  replayed: boolean;
}

const EVIDENCE_FILE = 'autogen/agentchat/conversable_agent.py';
const EVIDENCE_LINE = 17;

/**
 * 把一个课时"看到末尾"。
 *
 * ## 为什么用 K 快捷键，而不是点播放等它自己播完
 *
 * 实测（本轮真链路）：**无音频**时点「播放」后，`PlayerProvider` 那句
 *
 *     void audio.play().catch(() => setStatus('paused'))
 *
 * 会因为 `<audio>` 没有 `src` 而 reject（NotSupportedError），把刚置上的
 * `playing` 立刻改回 `paused`——于是时间轴停在末尾却**永远进不了 `ended`**，
 * 课程进度也就再也写不进库（spec §7.3 的"无音频走 estimated 推进"这条路径实际是断的）。
 * 这不是本节点能修的文件，但它会让 ③ 永远测不到，所以这里改走
 * **同一个产品里的另一条真实路径**：快捷键 `K`（= 下一步，快捷键面板里公开的）
 * 在最后一步上会执行 `nextStep()` 的末步分支 → `status = 'ended'`。
 *
 * 进度落库仍然由产品自己完成：离开课程页时 `PlayerProvider` 的
 * `beforeunload → persist(true)` 会用 `sendBeacon` 写 `/progress/beacon`。
 * 断言只负责"课时真的结束 + 进度真的落库"，不替产品算 percent。
 */
async function finishCurrentLesson(page: Page, lessonKey: string, courseId: string): Promise<void> {
  await page.goto(`/course/${encodeURIComponent(courseId)}/overview?lesson=${encodeURIComponent(lessonKey)}`);
  const scrubber = page.getByLabel('当前步骤进度');
  await expect(scrubber, '播放器必须已经加载出当前课时的时间轴').toBeVisible({ timeout: 30_000 });
  const max = Number(await scrubber.getAttribute('max'));
  expect(max, '首步时长必须大于 0，否则时间轴没有推进空间').toBeGreaterThan(0);

  await page.keyboard.press('KeyK');
  await expect(page.getByText('本节已看完'), '课时必须走到 ended，否则进度不会被持久化').toBeVisible({
    timeout: 30_000,
  });
}

test('T-E2E-R2 答题 → 证据跳转 → 重放幂等 → 完课页 percent', async ({ page, context, seededCourse }, testInfo) => {
  test.setTimeout(180_000);
  await bypassSetup(context);

  const courseId = seededCourse.id;
  const detail = await getJson<CourseDetail>(page, `/api/courses/${encodeURIComponent(courseId)}`);
  const allLessons = detail.sections.flatMap((section) => section.lessons);
  expect(allLessons.length, '演示课程必须有课时').toBeGreaterThan(0);

  // ---- ① 答题 → 解释 + 证据 → 跳到工作台且 file/line 生效 ----------------------
  await page.goto(`/course/${encodeURIComponent(courseId)}/walkthrough`);
  const answerButton = page.getByRole('button', { name: /^b\s*返回 None$/ });
  await expect(answerButton, '第二层必须出现演示课程的预测题').toBeVisible({ timeout: 30_000 });
  await answerButton.click();

  await expect(page.getByText('回答正确')).toBeVisible();
  const evidenceButton = page.getByRole('button', { name: /conversable_agent\.py:17/ });
  await expect(evidenceButton, '解释下面必须有可点击的"证据"（file:line）').toBeVisible();

  // 点证据 → 跨层跳转：会带着 ?file=&line= 打开第三层。
  await evidenceButton.click();
  await page.waitForURL(
    (url) =>
      url.pathname === `/course/${courseId}/deep-dive` &&
      url.searchParams.get('file') === EVIDENCE_FILE &&
      url.searchParams.get('line') === String(EVIDENCE_LINE),
    { timeout: 30_000 },
  );

  // 为什么这里要 reload 一次再断言"真的读了这个文件"：
  // 走读层的 CodePane 已经读过同一个文件，TanStack Query 命中缓存，
  // client-side 跳转**不应该**再发一次请求（那是正确行为）。冷启动一次
  // （深链仍在 URL 上）之后请求必然发生，这条断言才有意义。
  const freshFileRequest = page.waitForRequest(
    (request) =>
      request.url().includes('/files?path=') && decodeURIComponent(request.url()).includes(EVIDENCE_FILE),
    { timeout: 30_000 },
  );
  await page.reload();
  await freshFileRequest;

  await expect(
    page.getByRole('navigation', { name: '代码位置' }),
    '第三层的面包屑必须指向证据文件（说明 ?file= 真的生效了，而不只是停在了 URL 里）',
  ).toContainText('conversable_agent.py');
  await expect(
    page.getByText('class ConversableAgent').first(),
    '第三层必须真的把证据文件的正文渲染出来（?file= 生效的最终证据）',
  ).toBeVisible({ timeout: 30_000 });

  // ---- ② 同题二次提交：replayed=true 且不重复计数 -----------------------------
  await page.goto(`/course/${encodeURIComponent(courseId)}/walkthrough`);
  await expect(page.getByRole('button', { name: /^b\s*返回 None$/ })).toBeVisible({ timeout: 30_000 });
  const secondSubmit = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().includes('/quiz/'),
    { timeout: 30_000 },
  );
  await page.getByRole('button', { name: /^b\s*返回 None$/ }).click();
  const replayBody = (await (await secondSubmit).json()) as QuizAnswerResponse;
  expect(replayBody.replayed, '同题二次提交必须由真后端判定为 replayed=true（幂等键）').toBe(true);
  expect(replayBody.correct, '重放必须返回首次结果').toBe(true);
  await expect(page.getByText(/重复提交/), '界面必须明确说明这是重复提交').toBeVisible();

  const recap = await getJson<RecapResponse>(page, `/api/courses/${encodeURIComponent(courseId)}/recap`);
  expect(
    Number(recap.quiz_stats['answered']),
    '重复提交不能增加答题计数（quiz_stats.answered 必须还是 1）',
  ).toBe(1);

  // ---- ③ 完课页 percent 与已学课时数一致 -------------------------------------
  let learned = 0;
  for (const lesson of allLessons) {
    await finishCurrentLesson(page, lesson.key, courseId);
    learned += 1;
    if (learned === 1) {
      // 先单独验一次"学过就真的落库了"：只学完第一节时 percent 必须 > 0。
      // （这里**不**断言 == round(100×1/4)，因为产品的 percent 目前是"课时内进度"
      // 写进课程级字段，那样的断言会在今天立刻变红——见文件头与报告。）
      await page.goto('/');
      await expect
        .poll(async () => Number((await getJson<RecapResponse>(page, `/api/courses/${encodeURIComponent(courseId)}/recap`)).percent), {
          timeout: 20_000,
          message: '学完第一节后进度必须被持久化（beforeunload → sendBeacon → /progress/beacon）',
        })
        .toBeGreaterThan(0);
    }
  }

  const total = allLessons.length;
  const expectedPercent = Math.round((100 * learned) / total);

  // 最后一节学完后同样要靠"离开页面"把进度 beacon 送出去，再读完课页。
  await page.goto('/');
  await expect
    .poll(async () => Number((await getJson<RecapResponse>(page, `/api/courses/${encodeURIComponent(courseId)}/recap`)).percent), {
      timeout: 20_000,
      message: '全部学完后完课页 percent 必须落库',
    })
    .toBe(expectedPercent);

  const finalRecap = await getJson<RecapResponse>(page, `/api/courses/${encodeURIComponent(courseId)}/recap`);
  expect(
    finalRecap.percent,
    `完课页 percent（${finalRecap.percent}）必须等于 round(100 × 已学 ${learned}/${total}) = ${expectedPercent}`,
  ).toBe(expectedPercent);
  expect(finalRecap.completed, '全部学完后 completed 必须为 true').toBe(true);

  await page.goto(`/course/${encodeURIComponent(courseId)}/recap`);
  await expect(page.getByText(`${expectedPercent}%`).first(), '完课页必须展示 percent').toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText('知识点复盘').first()).toBeVisible();
  await testInfo.attach('recap.json', { body: JSON.stringify(finalRecap, null, 2), contentType: 'application/json' });
});
