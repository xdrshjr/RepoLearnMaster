/**
 * T-KRN-4：预算中断。
 *
 * 三个闸门各断言一次；另外断言"超限之后永久锁死"——允许超限后继续跑等于没有闸门。
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { Budget, BudgetExceeded, clampLimits, violatesAbsoluteLimits } from '../src/budget.ts';

test('turns 超限抛 turns', () => {
  const b = new Budget({ maxTurns: 2, maxTokens: 1000, maxUsd: 1, deadlineMs: 10_000 }, null, () => 0);
  b.beginTurn();
  b.beginTurn();
  assert.throws(() => b.beginTurn(), (e: unknown) => {
    assert.ok(e instanceof BudgetExceeded);
    assert.equal((e as BudgetExceeded).kind, 'turns');
    return true;
  });
});

test('tokens 超限抛 tokens 且不回退', () => {
  const b = new Budget({ maxTurns: 10, maxTokens: 100, maxUsd: 1, deadlineMs: 10_000 }, null, () => 0);
  b.record(400, { inputTokens: 90, outputTokens: 0 });
  assert.throws(() => b.record(400, { inputTokens: 90, outputTokens: 0 }), BudgetExceeded);
  // 已经超限后，哪怕下一次用量很小也必须继续抛
  assert.throws(() => b.tick(), BudgetExceeded);
});

test('usd 超限在已知价格时生效', () => {
  const b = new Budget({ maxTurns: 10, maxTokens: 1_000_000, maxUsd: 0.01, deadlineMs: 10_000 }, { input: 10, output: 30 }, () => 0);
  assert.equal(b.priceKnown, true);
  assert.throws(() => b.record(0, { inputTokens: 5000, outputTokens: 0 }), BudgetExceeded);
});

test('无价格时 usd 不计（PRICE_UNKNOWN 语义）', () => {
  const b = new Budget({ maxTurns: 10, maxTokens: 1_000_000, maxUsd: 0.0001, deadlineMs: 10_000 }, null, () => 0);
  assert.equal(b.priceKnown, false);
  b.record(0, { inputTokens: 900_000, outputTokens: 0 });
  assert.equal(b.usage.usd, 0);
});

test('deadline 用注入时钟推进', () => {
  let now = 0;
  const b = new Budget({ maxTurns: 10, maxTokens: 1000, maxUsd: 1, deadlineMs: 1000 }, null, () => now);
  now = 500;
  b.tick();
  now = 1500;
  assert.throws(() => b.tick(), (e: unknown) => (e as BudgetExceeded).kind === 'deadline');
});

test('没有 usage 回报时按字符数估算并标记 estimated', () => {
  const b = new Budget({ maxTurns: 10, maxTokens: 10_000, maxUsd: 1, deadlineMs: 10_000 }, null, () => 0);
  b.record(400, null);
  assert.equal(b.usage.usageSource, 'estimated');
  assert.equal(b.usage.tokensIn, 100);
});

test('clampLimits 收敛到安全默认值', () => {
  const l = clampLimits({ maxTokens: 999_999_999 });
  assert.equal(l.maxTokens, 4_000_000);
  assert.equal(l.maxTurns, 16);
});

test('显式超绝对上限被识别为违规（要 422，不是静默 clamp）', () => {
  assert.equal(violatesAbsoluteLimits({ maxTokens: 4_000_001 }), 'maxTokens=4000001 exceeds kernel ceiling 4000000');
  assert.equal(violatesAbsoluteLimits({ maxTokens: 2_000_000 }), null);
});
