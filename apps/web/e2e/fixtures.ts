/**
 * Offline E2E fixtures (spec §8.3 "离线 E2E").
 *
 * Every response here is a **hand-written** payload that matches
 * `apps/web/src/lib/api/types.ts`, so the tests prove the UI contract without a
 * backend, a database or an API key. Shapes deliberately include the awkward
 * parts (multiple segments, a step without audio, `timing_source: 'estimated'`)
 * because those are the branches that break first when the wire format drifts.
 */

import type { Page, Route } from '@playwright/test';

export const SETUP_COOKIE = { name: 'rl_setup', value: '1', path: '/' } as const;

export const COURSE_ID = 'cv_demo01';
export const LESSON_KEY = '1.1';

export const courseDetail = {
  id: COURSE_ID,
  repo: {
    full_name: 'facebook/react',
    owner: 'facebook',
    name: 'react',
    description: 'The library for web and native user interfaces',
    stars: 230000,
    license_spdx: 'MIT',
    primary_language: 'JavaScript',
    default_branch: 'main',
    html_url: 'https://github.com/facebook/react',
  },
  commit: { sha: 'a'.repeat(40), committed_at: '2024-12-01T00:00:00Z', file_count: 42 },
  title: 'React 带读课程',
  subtitle: '从宏观架构到源码细节',
  summary_md: '这是由静态分析生成的课程摘要。',
  status: 'ready',
  language: 'zh-CN',
  lesson_count: 2,
  minutes: 18,
  sections: [
    {
      key: 'overview',
      title: '宏观架构',
      minutes: 6,
      lessons: [
        { key: LESSON_KEY, title: '仓库结构与入口', layer: 'overview', minutes: 6, goal: '看清目录骨架' },
      ],
    },
    {
      key: 'walkthrough',
      title: '全局走读',
      minutes: 6,
      lessons: [
        { key: '2.1', title: '一次渲染的完整链路', layer: 'walkthrough', minutes: 6, goal: '跟一遍调用顺序' },
      ],
    },
    {
      key: 'deep_dive',
      title: '深入源码',
      minutes: 6,
      lessons: [
        { key: '3.1', title: 'reconciler 的核心循环', layer: 'deep_dive', minutes: 6, goal: '读懂调度' },
      ],
    },
  ],
  blueprint: { repo_full_name: 'facebook/react' },
  quality_report: { anchor_coverage: 0.93, degraded: false },
  warnings: [],
  cover_palette: 'mint',
  created_at: '2024-12-01T00:00:00Z',
  published_at: '2024-12-01T00:10:00Z',
};

export const lessonList = {
  sections: [
    {
      key: 'overview',
      title: '宏观架构',
      minutes: 6,
      lessons: [
        { key: LESSON_KEY, title: '仓库结构与入口', layer: 'overview', minutes: 6, goal: '看清目录骨架' },
      ],
    },
    {
      key: 'walkthrough',
      title: '全局走读',
      minutes: 6,
      lessons: [
        { key: '2.1', title: '一次渲染的完整链路', layer: 'walkthrough', minutes: 6, goal: '跟一遍调用顺序' },
      ],
    },
    {
      key: 'deep_dive',
      title: '深入源码',
      minutes: 6,
      lessons: [
        { key: '3.1', title: 'reconciler 的核心循环', layer: 'deep_dive', minutes: 6, goal: '读懂调度' },
      ],
    },
  ],
};

/** 每一层都返回同一份 bundle，但把 lesson.key 换成该层的课时 key。 */
export const playbackFor = (key: string, title: string, layer: string) => ({
  ...playbackBundle,
  lesson: { key, title, layer, minutes: 6 },
});

const segment = (id: string, text: string, start: number, end: number) => ({
  id,
  text,
  start_ms: start,
  end_ms: end,
  focus: { file: 'src/App.js', line_start: 1, line_end: 3 },
  board_actions: [],
  subtitle_style: 'normal',
});

export const playbackBundle = {
  course_id: COURSE_ID,
  commit_sha: 'a'.repeat(40),
  lesson: { key: LESSON_KEY, title: '仓库结构与入口', layer: 'overview', minutes: 6 },
  steps: [
    {
      index: 0,
      title: '第一步：先看目录骨架',
      duration_ms: 6000,
      // 第二步没有音频：播放器必须退化成"字幕推进"，这条分支最容易被写坏。
      timing_source: 'estimated',
      audio: null,
      segments: [
        segment('s0', '这是第一段字幕：先看仓库的顶层目录。', 0, 3000),
        segment('s1', '这是第二段字幕：再看入口文件。', 3000, 6000),
      ],
      board: null,
      code_notes: [],
      quiz: [],
      certainty_legend: { source_fact: '源码事实' },
    },
    {
      index: 1,
      title: '第二步：找到入口文件',
      duration_ms: 4000,
      timing_source: 'estimated',
      audio: null,
      segments: [segment('s2', '入口文件是 src/App.js。', 0, 4000)],
      board: null,
      code_notes: [],
      quiz: [
        {
          id: 'q_1',
          stem: '入口文件是哪一个？',
          choices: [
            { id: 'a', text: 'src/App.js' },
            { id: 'b', text: 'src/main.js' },
          ],
          answer_id: 'a',
          explanation_md: 'App.js 在 src 目录下被 render 调用。',
          evidence: [{ file: 'src/App.js', line_start: 1, line_end: 3 }],
        },
      ],
      certainty_legend: { source_fact: '源码事实' },
    },
  ],
  files: [{ path: 'src/App.js', content_ref: 'f1', lang: 'javascript', line_count: 3 }],
  trace: {
    id: 'tr_1',
    steps: [
      {
        index: 0,
        title: 'render 被调用',
        certainty: 'source_fact',
        evidence: [{ file: 'src/App.js', line_start: 1 }],
        variables: [],
        note: '来自源码',
      },
    ],
    certainty_summary: { source_fact: 1 },
  },
};

export const fileContent = {
  path: 'src/App.js',
  lang: 'javascript',
  line_count: 3,
  content: 'function App() {\n  return null;\n}\n',
  truncated: false,
};

export const recapResponse = {
  knowledge_points: [{ title: '入口文件', detail: 'src/App.js 是被 render 的根组件。' }],
  call_chain: { steps: ['index.js', 'App.js'] },
  pitfalls: ['不要把 reconciler 与 renderer 混为一谈'],
  quiz_stats: { answered: 1, correct: 1 },
  next_steps: ['去读 react-reconciler 的 beginWork'],
  ability: { 结构理解: 0.8, 调用链追踪: 0.7 },
  completed: true,
  percent: 100,
};

export const jobDetail = {
  id: 'job_demo01',
  kind: 'course',
  status: 'running',
  progress: 62,
  node: 'write_lessons',
  message: '正在撰写课时',
  course_id: COURSE_ID,
  book_id: null,
  started_at: '2024-12-01T00:00:00Z',
  finished_at: null,
  error: null,
  cost: { tokens: 12000, usd: 0.03 },
  created_at: '2024-12-01T00:00:00Z',
  attempts: 1,
};

/** JSON helper that also proves the BFF never had to reach a backend. */
export async function fulfilJson(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify(body),
  });
}

/**
 * One route handler for the whole `/api/**` surface.
 *
 * Ordering matters: Playwright routes are LIFO, so registering this single
 * catch-all (instead of a dozen globs) makes the "which mock wins" question go
 * away entirely.
 */
export async function mockApi(page: Page, overrides: Record<string, unknown> = {}): Promise<void> {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    const key = `${method} ${path}`;
    if (key in overrides) {
      const value = overrides[key];
      if (value instanceof Object && 'status' in (value as Record<string, unknown>)) {
        const spec = value as { status: number; body: unknown };
        await fulfilJson(route, spec.body, spec.status);
        return;
      }
      await fulfilJson(route, value);
      return;
    }

    if (path === '/api/healthz') {
      await fulfilJson(route, { status: 'ok', db: true, kernel: 'template', migration: 'ok', gates: {} });
      return;
    }
    if (path === '/api/setup/state') {
      await fulfilJson(route, {
        required: false,
        active_profile: { id: 'lp_1', provider: 'anthropic', models: ['claude-sonnet-4-5'], is_active: true, created_at: null },
        profiles: [],
        gates: { g1: 'ok', g2: 'ok', g3: 'ok' },
        kernel: { mode: 'template', reason: 'offline e2e', core_version: null },
      });
      return;
    }
    if (path === '/api/courses' && method === 'GET') {
      await fulfilJson(route, { items: [courseDetail], next_cursor: null });
      return;
    }
    if (path === '/api/courses' && method === 'POST') {
      await fulfilJson(route, { course_id: COURSE_ID, job_id: 'job_demo01', reused: false, status_url: '/v1/jobs/job_demo01' }, 202);
      return;
    }
    if (path === `/api/courses/${COURSE_ID}`) {
      await fulfilJson(route, courseDetail);
      return;
    }
    if (path === `/api/courses/${COURSE_ID}/lessons`) {
      await fulfilJson(route, lessonList);
      return;
    }
    const playbackMatch = path.match(new RegExp(`^/api/courses/${COURSE_ID}/lessons/([^/]+)/playback$`));
    if (playbackMatch) {
      const key = decodeURIComponent(playbackMatch[1] ?? LESSON_KEY);
      const layer =
        key === '2.1' ? 'walkthrough' : key === '3.1' ? 'deep_dive' : 'overview';
      const title =
        key === '2.1' ? '一次渲染的完整链路' : key === '3.1' ? 'reconciler 的核心循环' : '仓库结构与入口';
      await fulfilJson(route, playbackFor(key, title, layer));
      return;
    }
    if (path === `/api/courses/${COURSE_ID}/files`) {
      await fulfilJson(route, fileContent);
      return;
    }
    if (path === `/api/courses/${COURSE_ID}/recap`) {
      await fulfilJson(route, recapResponse);
      return;
    }
    if (path === `/api/courses/${COURSE_ID}/progress` && method === 'PUT') {
      await fulfilJson(route, { percent: 40, lesson_key: LESSON_KEY, step_index: 1, position_ms: 1000 });
      return;
    }
    if (path === `/api/courses/${COURSE_ID}/progress/beacon`) {
      await route.fulfill({ status: 204, body: '' });
      return;
    }
    if (/^\/api\/courses\/[^/]+\/quiz\/[^/]+\/answer$/.test(path)) {
      await fulfilJson(route, { correct: true, explanation_md: '对，App.js 是入口。', evidence: [], replayed: false });
      return;
    }
    if (path === '/api/jobs') {
      await fulfilJson(route, { items: [jobDetail], next_cursor: null });
      return;
    }
    if (path.startsWith('/api/jobs/')) {
      await fulfilJson(route, jobDetail);
      return;
    }
    if (path.startsWith('/api/sse/jobs/')) {
      // 一帧真实形状的 SSE：证明 BFF/前端解析的是"流"，不是"等结束的 JSON"。
      const frame =
        'id: 1\nevent: job.phase\ndata: {"schemaVersion":1,"type":"job.phase","seq":1,"ts":0,' +
        '"jobId":"job_demo01","runId":null,"data":{"node":"write_lessons","progress":62}}\n\n';
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache' },
        body: frame,
      });
      return;
    }
    if (path === '/api/settings/doctor') {
      await fulfilJson(route, { checks: [{ name: '数据库', status: 'ok', detail: 'sqlite', hint: null }] });
      return;
    }
    if (path === '/api/settings/revisions') {
      await fulfilJson(route, { items: [] });
      return;
    }
    if (path === '/api/metrics') {
      await fulfilJson(route, {
        jobs: { total: 1, by_status: { ready: 1 }, success_rate: 1, p50_seconds: 12, p95_seconds: 20 },
        cache: { courses: 1, readable_courses: 1, reuse_rate: 1 },
        providers: { tokens: 12000, usd: 0.03, since: null },
        learning: { quiz_answered: 1, quiz_accuracy: 1, courses_started: 1, courses_completed: 1, completion_rate: 1, pdf_exports: 0, books_with_pdf: 0 },
        generated_at: null,
      });
      return;
    }
    // 未知端点：显式 404（而不是 hang），这样"少 mock 一个接口"会立刻暴露成断言失败。
    await fulfilJson(route, { error: { code: 'OBJECT_MISSING', message: `no mock for ${key}`, retryable: false } }, 404);
  });
}

/** The first-run guard is cookie based; E2E starts as an "already configured" user. */
export async function visitConfigured(page: Page, path: string): Promise<void> {
  // 只给 url（Playwright 不允许同时给 url 与 path）。
  await page.context().addCookies([
    { name: SETUP_COOKIE.name, value: SETUP_COOKIE.value, url: 'http://127.0.0.1:3000' },
  ]);
  await page.goto(path);
}
