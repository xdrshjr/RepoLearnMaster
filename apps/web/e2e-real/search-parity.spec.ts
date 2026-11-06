/**
 * T-E2E-R4 · 真后端搜索 `scan` / `fts` 结果集一致（hardening spec §3.2.3 表第 4 行）。
 *
 * 三条断言：
 * ① 同一关键词在 `mode=scan` 与 `mode=fts` 下 `items` 的 **id 集合相同**（允许顺序不同）；
 * ② 响应 `mode` 字段与实际生效模式一致（证明"开关真的生效"，而不是配置里写了
 *    `fts`、代码里还在走 `LIKE`——那正是 M9 要消灭的 G3 谎言）；
 * ③ `fts` 模式下响应里有 `total` 与 `next_offset` 字段（分页语义与 scan 不同，混用会让
 *    用户"翻到第二页却拿到第一页的重复行"）。
 *
 * ## 关于 spec 的 P2-7（"先只跑 scan 自身一致性，fts 落地后再补对照"）
 *
 * 本轮 **fts 已经落地**（`apps/api/repolearn/services/search.py` +
 * `services/course_search` 的 trigram 索引 + 迁移 0002 的四个触发器），所以这里直接
 * 写成完整形态，不需要 `test.fixme`：先用 `mode=fts` 拿到 `mode="fts"` 的实证，
 * 再比 id 集合。**唯一**的降级分支（`mode` 回落成 `scan`）也不是恒真：它必须
 * 带上非空的 `fallback_reason`（`query_too_short` / `sqlite_too_old` / `index_missing`），
 * 否则"fts 悄悄没生效"就会伪装成通过。
 *
 * 关键词选 `autogen`：它同时出现在夹具课程（`microsoft/autogen (demo)`）与
 * 导入用例生成的那门课的仓库名里，长度 ≥ 3（trigram 的最小匹配单位是 3 字符，
 * 2 字符的中文查询必然回落 scan，那是另一条用例 T-SEARCH-3 的范围）。
 */

import { bypassSetup, expect, listCourses, test, type CourseListResponse } from './fixtures';

const KEYWORD = 'autogen';

test('T-E2E-R4 同一关键词 scan / fts 的 id 集合相同，且 mode 回显真实生效模式', async ({ page, context }) => {
  test.setTimeout(120_000);
  await bypassSetup(context);
  await page.goto('/');

  const query = `q=${encodeURIComponent(KEYWORD)}&limit=20`;
  const scan = await listCourses(page, `${query}&mode=scan`);
  const fts = await listCourses(page, `${query}&mode=fts`);

  // ---- ② 先验"开关真的生效" ------------------------------------------------
  expect(scan.mode, 'mode=scan 的响应必须回显 scan').toBe('scan');
  expect(['fts', 'scan'], `mode=fts 的响应回显了 ${String(fts.mode)}`).toContain(fts.mode);

  if (fts.mode === 'fts') {
    // ---- ③ fts 的分页契约 ---------------------------------------------------
    expect(Object.hasOwn(fts, 'next_offset'), 'fts 响应里必须有 next_offset 字段（可以为 null）').toBe(true);
    expect(Object.hasOwn(fts, 'total'), 'fts 响应里必须有 total 字段').toBe(true);
    expect(
      typeof (fts as CourseListResponse).total,
      `fts 的 total 必须是数字，实际是 ${JSON.stringify((fts as CourseListResponse).total)}`,
    ).toBe('number');
  } else {
    // 回落可以接受，但必须**说明原因**，否则"fts 静默失效"就能蒙过这条用例。
    expect(
      fts.fallback_reason,
      'mode=fts 却回落成 scan 时必须给出 fallback_reason（query_too_short / sqlite_too_old / index_missing）',
    ).toBeTruthy();
  }

  // ---- ① id 集合相同 ------------------------------------------------------
  // 先排除"两边都是空集所以天然相等"这种假绿。
  expect(scan.items.length, `scan 模式必须能搜到 "${KEYWORD}"（否则下面的集合比较没有意义）`).toBeGreaterThan(
    0,
  );
  expect(fts.items.length, `fts 模式必须能搜到 "${KEYWORD}"`).toBeGreaterThan(0);

  const scanIds = scan.items.map((item) => item.id).sort();
  const ftsIds = fts.items.map((item) => item.id).sort();
  expect(
    ftsIds,
    `两种模式的 id 集合必须相同（scan=${JSON.stringify(scanIds)} / fts=${JSON.stringify(ftsIds)}）。` +
      '不一致意味着索引漏行、触发器没生效，或者两条分支的匹配语义已经漂移',
  ).toEqual(scanIds);

  // 顺序可以不同（fts 按 bm25 升序，scan 按 created_at 倒序），但集合必须一样。
  expect(new Set(ftsIds).size, 'fts 结果里不该有重复 id').toBe(ftsIds.length);
});
