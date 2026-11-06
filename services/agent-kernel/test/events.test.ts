/**
 * T-KRN-3：事件映射。用**假的 stream 事件**驱动，不需要任何 provider。
 *
 * 断言的是"契约"，不是"实现"：未知事件必须被丢弃而不是抛错（spec §5.5 规则 3），
 * seq 必须从 1 开始单调递增（规则 1）。
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { envelope, makeEnvelopeContext, mapCoreEvent, toSseFrame } from '../src/events.ts';

test('seq 从 1 开始且单调递增', () => {
  const ctx = makeEnvelopeContext('run_1', 'job_1', () => 1000);
  const a = envelope(ctx, 'system.init', {});
  const b = envelope(ctx, 'agent.text.delta', { delta: 'x' });
  assert.equal(a.seq, 1);
  assert.equal(b.seq, 2);
  assert.equal(a.ts, 1000);
  assert.equal(a.schemaVersion, 1);
});

test('SSE 帧第一行是 id: <seq>', () => {
  const ctx = makeEnvelopeContext('run_1', null, () => 1);
  const frame = toSseFrame(envelope(ctx, 'agent.text.delta', { delta: 'hi' }));
  assert.match(frame, /^id: 1\nevent: agent\.text\.delta\ndata: \{/);
  assert.ok(frame.endsWith('\n\n'));
});

test('text_delta 映射为 agent.text.delta', () => {
  const ctx = makeEnvelopeContext('run_1', null);
  const out = mapCoreEvent(ctx, { type: 'message_update', streamEvent: { type: 'text_delta', delta: 'abc' } });
  assert.equal(out.length, 1);
  assert.equal(out[0]?.type, 'agent.text.delta');
  assert.deepEqual(out[0]?.data, { delta: 'abc' });
});

test('未知事件类型被丢弃且不抛错（向后兼容）', () => {
  const ctx = makeEnvelopeContext('run_1', null);
  assert.deepEqual(mapCoreEvent(ctx, { type: 'some_future_event', foo: 1 }), []);
  assert.deepEqual(mapCoreEvent(ctx, { type: 'message_update', streamEvent: { type: 'brand_new' } }), []);
});

test('工具事件映射为 tool.start / tool.end', () => {
  const ctx = makeEnvelopeContext('run_1', null);
  const start = mapCoreEvent(ctx, {
    type: 'tool_execution_start',
    toolName: 'repo_read_file',
    toolCallId: 'c1',
    args: { file: 'a.py' },
  });
  assert.equal(start[0]?.type, 'tool.start');
  const end = mapCoreEvent(ctx, {
    type: 'tool_execution_end',
    toolCallId: 'c1',
    toolName: 'repo_read_file',
    isError: false,
    result: { content: [{ type: 'text', text: '{"truncated": true}' }] },
  });
  assert.equal(end[0]?.type, 'tool.end');
  assert.equal((end[0]?.data as { truncated: boolean }).truncated, true);
});
