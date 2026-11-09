// @vitest-environment node
/**
 * 首启守卫 cookie 的自愈回归（spec §3.6.1 规则 1）。
 *
 * 真实故障（浏览器实测）：清掉站点数据后再打开 `http://localhost:3000/`，
 * 中间件把请求 307 到 `/setup?next=%2F`；`/setup` 调 `/api/setup/state` 得到
 * `required:false`，于是渲染"已配置完成"，唯一的按钮是「回首页」，点下去
 * 又被 307 回 `/setup`——**整个应用不可用，且没有任何页面能修它**。
 *
 * 根因：`rl_setup` 只由 `POST /api/setup/commit` 的成功响应写入，而配置完成的
 * 用户不会再有第二次提交。修复点是 `/api/setup/state`：它自己的响应体就写着
 * "是否还缺配置"，所以 `required:false` 时必须顺手补写 cookie。
 *
 * 这个文件显式声明 node 环境：BFF 依赖服务端 `fetch` 与 `process.env`。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { proxyRequest } from '@/lib/api/bff';
import { SETUP_COOKIE } from '@/lib/api/constants';

function upstreamResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function fakeRequest(path: string, init: { method?: string; search?: string } = {}): never {
  const url = `http://localhost:3000${path}${init.search ?? ''}`;
  const request = {
    method: init.method ?? 'GET',
    nextUrl: { search: init.search ?? '', protocol: 'http:' },
    headers: new Headers(),
    arrayBuffer: async () => new ArrayBuffer(0),
    cookies: { get: () => undefined },
    url,
  };
  return request as never;
}

function setupCookieOf(response: Response): string | null {
  const cookies = response.headers.getSetCookie?.() ?? [];
  return cookies.find((cookie) => cookie.startsWith(`${SETUP_COOKIE}=`)) ?? null;
}

describe('BFF 首启守卫 cookie', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    process.env.REPOLEARN_API_BASE = 'http://127.0.0.1:8000';
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it('GET /setup/state 返回 required:false 时补写 rl_setup（自愈）', async () => {
    fetchMock.mockResolvedValue(upstreamResponse({ required: false, steps_done: [1, 2, 3, 4, 5] }));

    const response = await proxyRequest(fakeRequest('/api/setup/state'), { segments: ['setup', 'state'] });

    expect(response.status).toBe(200);
    expect(setupCookieOf(response)).not.toBeNull();
    // 响应体必须原样透传：自愈不能以"读掉 body"为代价。
    expect(await response.text()).toContain('"required":false');
  });

  it('GET /setup/state 返回 required:true 时**不**写 cookie（否则首次配置永远被跳过）', async () => {
    fetchMock.mockResolvedValue(upstreamResponse({ required: true, steps_done: [] }));

    const response = await proxyRequest(fakeRequest('/api/setup/state'), { segments: ['setup', 'state'] });

    expect(setupCookieOf(response)).toBeNull();
    expect(await response.text()).toContain('"required":true');
  });

  it('POST /setup/commit 成功仍然写 cookie（原有行为不能被自愈改坏）', async () => {
    fetchMock.mockResolvedValue(upstreamResponse({ profile_id: 'prf_x', revision: 2, warnings: [] }));

    const response = await proxyRequest(fakeRequest('/api/setup/commit', { method: 'POST' }), {
      segments: ['setup', 'commit'],
    });

    expect(setupCookieOf(response)).not.toBeNull();
  });

  it('上游失败（5xx）时不写 cookie，也不吞掉错误体', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: { code: 'INTERNAL', message: 'boom' } }), {
        status: 500,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const response = await proxyRequest(fakeRequest('/api/setup/state'), { segments: ['setup', 'state'] });

    expect(setupCookieOf(response)).toBeNull();
    expect(await response.text()).toContain('boom');
  });
});
