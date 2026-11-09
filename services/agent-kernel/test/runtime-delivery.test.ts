/**
 * 交付物必须跟着失败事件走（2026-11-09 真机复现）。
 *
 * 现场：planner 第 6 轮起把 `repo_file_outline` / `repo_read_file` 读了一轮又一轮，
 * 第 10 轮 `emit_course_json` **已经 accepted**，第 11 轮想再说点什么时 `maxTurns`
 * 撞顶。内核发出去的 `run.failed` 里只有 code/message，没有 result —— 于是
 * Python 侧拿到一个"规划失败"的空结果，整门课静默降级成模板版，而完整骨架其实
 * 就躺在 EmitSlot 里。
 *
 * 这条规则必须由**纯函数**守住：它在真实事件流里看不出来（症状只是"课程变简化版"）。
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { failedRunData } from '../src/runtime.ts';

const USAGE = { turns: 11, tokens: 208112, usd: 0 };

test('预算触顶时，已交付的课程骨架仍然随 run.failed 一起返回', () => {
  const curriculum = { title: 'sherlock 带读', sections: [{ key: 'overview', lessons: [] }] };
  const data = failedRunData({
    code: 'BUDGET_EXCEEDED',
    message: 'budget exceeded: turns used=11 limit=10',
    retryable: false,
    usage: USAGE,
    delivered: { curriculum, lessons: {}, traces: {}, quizzes: {}, failures: [] },
  });

  assert.equal(data.code, 'BUDGET_EXCEEDED');
  assert.deepEqual((data.result as Record<string, unknown>).curriculum, curriculum);
  // usage 不能被失败事件吞掉：cost_ledger 靠它记账
  assert.deepEqual(data.usage, USAGE);
});

test('什么都没交付时不上报 result（避免"交付了一个空对象"的假象）', () => {
  const data = failedRunData({
    code: 'PROVIDER_UNAVAILABLE',
    message: 'idle timeout',
    retryable: true,
    usage: USAGE,
    delivered: { curriculum: null, lessons: {}, traces: {}, quizzes: {}, failures: [] },
  });

  assert.ok(!('result' in data));
  assert.equal(data.retryable, true);
});

test('delivered 为 undefined 时不崩（取消/异常路径不传它）', () => {
  const data = failedRunData({ code: 'X', message: 'm', retryable: false, usage: {} });
  assert.ok(!('result' in data));
});
