/**
 * T-KRN-2/4 回归：三个"看起来在跑、其实没生效"的通道。
 *
 * 这三条都不是功能缺失，而是**语义错位**：`req.tools` 被当成完整白名单、
 * 上报的 usage 被丢弃、abort 之后的 reject 被当成可重试失败。它们的共同症状
 * 是"模型好像不听话 / 预算好像没闸门 / 取消好像没反应"，从日志里看不出来。
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { Budget } from '../src/budget.ts';
import { resolveAllowedTools } from '../src/runtime.ts';

test('req.tools 只列 repo 工具时，emit_* 仍必须可用（否则永远 CONTRACT_VIOLATION）', () => {
  const allowed = resolveAllowedTools(['repo_list_tree', 'repo_read_file', 'repo_grep', 'repo_file_outline']);
  assert.ok(allowed.includes('emit_course_json'));
  assert.ok(allowed.includes('emit_lesson'));
  assert.ok(allowed.includes('emit_trace'));
});

test('req.tools 为空时使用默认工具集（含 emit_*）', () => {
  const allowed = resolveAllowedTools(null);
  assert.ok(allowed.includes('repo_grep'));
  assert.ok(allowed.includes('emit_trace'));
});

test('req.tools 里的未知工具不会被悄悄并入白名单', () => {
  const allowed = resolveAllowedTools(['repo_read_file', 'shell_exec']);
  assert.ok(!allowed.includes('shell_exec'));
  assert.ok(allowed.includes('repo_read_file'));
});

test('多轮 record 的 usd 是总价，不是逐轮累加（否则闸门提前触发）', () => {
  const price = { input: 1, output: 0 }; // 1 USD / 1M token
  const budget = new Budget({ maxTurns: 10, maxTokens: 1_000_000, maxUsd: 100, deadlineMs: 10_000 }, price, () => 0);
  budget.record(0, { inputTokens: 1000, outputTokens: 0 });
  budget.record(0, { inputTokens: 1000, outputTokens: 0 });
  // 2000 token × 1 USD/1M = 0.002 USD。累加式实现会得到 0.003。
  assert.equal(budget.usage.usd, 0.002);
  assert.equal(budget.usage.tokensIn, 2000);
});

test('上报 usage 后 tokensIn 不再为 0（token 闸门要数输入侧）', () => {
  const budget = new Budget({ maxTurns: 10, maxTokens: 10_000, maxUsd: 1, deadlineMs: 10_000 }, null, () => 0);
  // 真实顺序：先按文本增量估输出，再在 turn_end 补真实输入
  budget.recordOutputTokens(10);
  budget.record(0, { inputTokens: 4321, outputTokens: 0 });
  assert.equal(budget.usage.tokensIn, 4321);
  assert.equal(budget.usage.usageSource, 'mixed');
});
