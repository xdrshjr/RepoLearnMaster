/**
 * 交付即收工 + 输出 token 对账（2026-11-09 真机复现）。
 *
 * 现场：单课时 writer run 花掉 150k+ input tokens、**输出 token 记为 0**，
 * 正好撞上 `NODE_BUDGETS["write_lessons"]=150_000` 的节点分闸 —— 而课时其实
 * 已经在第 10 轮 `emit_lesson` 成功交付了。两个独立缺陷叠在一起：
 *
 * 1. `emit_*` 成功之后模型还会再开一轮（"总结一句"），每轮都要重发整段上下文。
 *    交付就是终态，所以 Kernel 现在在 emit 成功瞬间 abort，并把这次 run 判成
 *    `completed`（已交付不能因为"不再多说一句"而变成超预算）。
 * 2. `turn_end` 上报的 `outputTokens` 被写死传 0（注释说"已由 text_delta 累加"），
 *    但**工具调用不产生 text_delta**：只会 emit JSON 的 run 输出侧永远记 0，
 *    于是 cost_ledger 记 `tokens_out=0` / `usd=0`，成本面板与成本闸门双双失效。
 *
 * 这里守的是"交付通道是终态"与"输出侧按差值补齐"两条不变量。
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { createEmitSlot, createEmitTools } from '../src/tools/emit.ts';

const here = dirname(fileURLToPath(import.meta.url));
const runtimeSrc = readFileSync(resolve(here, '../src/runtime.ts'), 'utf8');

const VALID_CURRICULUM = {
  title: 'sherlock 带读',
  sections: [
    { key: 'overview', title: '宏观', lessons: [{ key: '1.1', title: 'a', goal: 'g' }] },
    { key: 'walkthrough', title: '走读', lessons: [{ key: '2.1', title: 'b', goal: 'g' }] },
    { key: 'deep_dive', title: '深入', lessons: [{ key: '3.1', title: 'c', goal: 'g' }] },
    { key: 'recap', title: '总结', lessons: [{ key: '4.1', title: 'd', goal: 'g' }] },
  ],
  summary_md: 'x',
};

test('emit_course_json 成功后触发 onDelivered（交付通道是终态）', async () => {
  const slot = createEmitSlot();
  const delivered: string[] = [];
  slot.onDelivered = (tool) => delivered.push(tool);

  const tools = createEmitTools(slot);
  const emitCourse = tools.find((t) => (t as { name: string }).name === 'emit_course_json') as unknown as {
    execute: (id: string, args: Record<string, unknown>) => Promise<unknown>;
  };
  await emitCourse.execute('call_1', VALID_CURRICULUM);

  assert.deepEqual(delivered, ['emit_course_json']);
  assert.ok(slot.curriculum, '骨架必须已经进槽');
});

test('emit 失败时不触发 onDelivered（否则会把一次失败当成交付）', async () => {
  const slot = createEmitSlot();
  const delivered: string[] = [];
  slot.onDelivered = (tool) => delivered.push(tool);

  const tools = createEmitTools(slot);
  const emitCourse = tools.find((t) => (t as { name: string }).name === 'emit_course_json') as unknown as {
    execute: (id: string, args: Record<string, unknown>) => Promise<unknown>;
  };
  await emitCourse.execute('call_1', { title: 'x', sections: [] });

  assert.deepEqual(delivered, []);
  assert.equal(slot.failures.length, 1);
});

test('runtime 把"已交付"当作成功终态，而不是失败/超预算', () => {
  assert.ok(runtimeSrc.includes('slot.onDelivered'), '必须接线到 EmitSlot');
  const deliveredBlocks = runtimeSrc.match(/deliverySucceeded && !budgetTripped/g) ?? [];
  assert.ok(deliveredBlocks.length >= 2, 'try 与 catch 两条路径都要判"已交付"');
  assert.ok(
    runtimeSrc.includes("abortReason = 'delivered'"),
    '要有一个独立的 abort 原因，不能借用 budget/cancelled',
  );
});

test('上报的输出 token 按 text_delta 差值补齐（否则 usd 恒为 0）', () => {
  assert.ok(runtimeSrc.includes('deltaOutThisTurn'), '必须记录本轮已估的输出 token');
  assert.ok(
    /outputTokens: Math\.max\(0, Math\.max\(0, usage\.outputTokens \?\? 0\) - deltaOutThisTurn\)/.test(runtimeSrc),
    'turn_end 不能再把 outputTokens 写死为 0',
  );
});
