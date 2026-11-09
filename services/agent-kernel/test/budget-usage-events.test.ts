/**
 * 预算事件的 **usage 传播**（真实故障回归）。
 *
 * 现场（var/logs/api.log，job_01M6Z6GDK7JGRMH1THMNP18CD0）：
 *
 *   kernel 侧：budget exceeded: tokens used=213725 limit=200000
 *   Python 侧 cost_ledger：tokens_in=0 tokens_out=0 usd=0
 *
 * 同一件事，两边记的是两个数。原因是 `budget.exceeded` 与 `run.failed` 两个
 * envelope 都**没有带 usage**，Python 只能记 0。后果不是"报表难看"：
 * job 级总闸靠 `charge()` 累积，记 0 就永远不会触发；成本面板与 /v1/metrics
 * 也全是 0。这条用例把"预算事件必须带 usage"钉在源码层面。
 *
 * 2026-11-09 之后两个 envelope 的构造被抽进了 `failedRunData()`，所以匹配方式
 * 从"`envelope(ctx, 'run.failed'` 之后的文本"改成"`'run.failed'` 字面量周围的
 * 窗口"——断言的目标没变：**同一处必须同时给出 usage 与已交付的 result**。
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const runtimeSrc = readFileSync(resolve(here, '../src/runtime.ts'), 'utf8');

/** 抓出每个事件名字面量周围的窗口（前 120 / 后 600 字符）。 */
function windowsAround(pattern: RegExp): string[] {
  const out: string[] = [];
  for (const match of runtimeSrc.matchAll(pattern)) {
    const start = Math.max(0, (match.index ?? 0) - 120);
    out.push(runtimeSrc.slice(start, (match.index ?? 0) + 600));
  }
  return out;
}

test('budget.exceeded 事件带 usage（否则 Python 侧账本记 0）', () => {
  const blocks = windowsAround(/'budget\.exceeded'/g);
  assert.ok(blocks.length >= 2, `期望至少 2 处 budget.exceeded，实际 ${blocks.length}`);
  for (const block of blocks) {
    assert.ok(block.includes('usage:'), `budget.exceeded 缺少 usage：${block.slice(0, 160)}`);
  }
});

test('BUDGET_EXCEEDED 的 run.failed 事件带 usage 与已交付的 result', () => {
  const blocks = windowsAround(/'run\.failed'/g).filter((b) => b.includes('BUDGET_EXCEEDED'));
  assert.ok(blocks.length >= 2, `期望至少 2 处 BUDGET_EXCEEDED 的 run.failed，实际 ${blocks.length}`);
  for (const block of blocks) {
    assert.ok(block.includes('usage:'), `BUDGET_EXCEEDED 的 run.failed 缺少 usage：${block.slice(0, 160)}`);
    // 交付物与终态是两条线：预算触顶时已经 emit 成功的骨架必须一起回传，
    // 否则 Python 侧会把"已经规划好的课"判成"规划失败"（见 runtime-delivery.test.ts）。
    assert.ok(
      block.includes('delivered:'),
      `BUDGET_EXCEEDED 的 run.failed 缺少已交付产出：${block.slice(0, 200)}`,
    );
  }
});

test('run.completed 仍然带 usage（正常路径的账本来源）', () => {
  // 预算事件带 usage 之后，正常完成路径不能因此被改坏：它是 cost_ledger 的
  // 主要来源，缺了它"成功但没记账"就会变成常态。
  const blocks = windowsAround(/'run\.completed'/g);
  assert.ok(blocks.length >= 1, `期望至少 1 处 run.completed，实际 ${blocks.length}`);
  for (const block of blocks) {
    assert.ok(block.includes('usage'), `run.completed 缺少 usage：${block.slice(0, 160)}`);
  }
});
