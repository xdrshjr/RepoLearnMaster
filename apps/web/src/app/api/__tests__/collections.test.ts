// @vitest-environment node
/**
 * 路由覆盖的防回归测试（spec §3.3 / §7.5）。
 *
 * 这条测试来自一个真实 bug：`app/api/courses/[...path]/route.ts` 只匹配
 * **带至少一段路径**的请求，于是 `GET /api/courses` 与 `POST /api/courses`
 * （首页列表 + 创建课程）直接 404 —— 而 Next 返回的是 404 页面 HTML，
 * 浏览器里表现为"接口返回了一段 HTML"，非常容易被误判成后端问题。
 *
 * 规则：客户端调用的每一个"集合路径"都必须在 `app/api/<name>/route.ts` 有一个
 * 同名文件，catch-all 不能替代。
 *
 * 这个文件显式声明 node 环境：默认的 jsdom 环境会把 `node:path` 换成浏览器 shim，
 * 在那里 `join` 不存在。
 */

import { existsSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const apiRoot = join(process.cwd(), 'src', 'app', 'api');

/** 客户端会以"集合"形式请求的路径（见 lib/api/hooks.ts）。 */
const COLLECTIONS = ['courses', 'jobs'];

describe('BFF collection routes', () => {
  it.each(COLLECTIONS)('有 %s 的集合路由（catch-all 不够）', (name) => {
    const file = join(apiRoot, name, 'route.ts');
    expect(existsSync(file), `缺少 ${file}：/api/${name} 会 404`).toBe(true);
  });

  it('catch-all 目录仍然存在（子路径转发）', () => {
    for (const name of COLLECTIONS) {
      expect(existsSync(join(apiRoot, name, '[...path]', 'route.ts'))).toBe(true);
    }
  });
});
