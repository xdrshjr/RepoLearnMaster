/**
 * T-KRN-6：schema 拒绝。
 *
 * 断言的是"错误会被回灌给模型"这一机制：`isError:true` + 可读的错误字符串。
 * 如果 schema 太严导致永远校验失败，这些测试会先炸——这正是我们想要的信号。
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { createEmitSlot, createEmitTools, schemaJson } from '../src/tools/emit.ts';
import { readPayload, type ToolResultLike } from '../src/tools/result.ts';

interface RawTool {
  name: string;
  execute: (toolCallId: string, params: Record<string, unknown>, context: object) => Promise<ToolResultLike>;
}

async function call(tools: unknown[], name: string, params: Record<string, unknown>) {
  const tool = tools.find((t) => (t as { name: string }).name === name) as RawTool | undefined;
  assert.ok(tool, `tool ${name} missing`);
  const result = await tool.execute('call-1', params, {});
  const text = result.content[0]?.type === 'text' ? result.content[0].text : '';
  return { result, payload: readPayload(result), text };
}

const goodCurriculum = {
  title: 'AutoGen 入门',
  sections: [
    { key: 'overview', title: '宏观架构', lessons: [{ key: '1.1', title: '整体结构', goal: '看懂分层' }] },
  ],
};

test('emit_course_json 接受最小合法骨架', async () => {
  const slot = createEmitSlot();
  const tools = createEmitTools(slot);
  const { payload } = await call(tools, 'emit_course_json', goodCurriculum);
  assert.equal(payload.accepted, true);
  assert.ok(slot.curriculum);
  assert.equal(slot.failures.length, 0);
});

test('emit_course_json 拒绝缺 sections 的产出并把错误回灌', async () => {
  const slot = createEmitSlot();
  const tools = createEmitTools(slot);
  const { result, text } = await call(tools, 'emit_course_json', { title: 'x' });
  assert.equal(result.isError, true);
  assert.match(text, /sections/);
  assert.equal(slot.failures.length, 1);
});

const goodLesson = {
  key: '1.1',
  title: '整体结构',
  layer: 'overview',
  steps: [
    {
      index: 0,
      title: '先看入口',
      duration_ms: 10_000,
      segments: [{ id: 's0', text: '这里从入口开始。', start_ms: 0, end_ms: 10_000 }],
    },
  ],
  quiz: [
    {
      id: 'q1',
      stem: '入口在哪？',
      choices: [
        { id: 'a', text: 'A' },
        { id: 'b', text: 'B' },
      ],
      answer_id: 'a',
      explanation_md: '因为…',
      evidence: [{ file: 'pkg/mod.py', line_start: 1, line_end: 2 }],
    },
  ],
};

test('emit_lesson 接受合法课时并按 key 归档', async () => {
  const slot = createEmitSlot();
  const tools = createEmitTools(slot);
  const { payload } = await call(tools, 'emit_lesson', goodLesson);
  assert.equal(payload.accepted, true);
  assert.equal(payload.key, '1.1');
  assert.ok(slot.lessons['1.1']);
  assert.equal(slot.quizzes['1.1']?.length, 1);
});

test('emit_lesson 拒绝 quiz 缺少 evidence', async () => {
  const slot = createEmitSlot();
  const tools = createEmitTools(slot);
  const bad = structuredClone(goodLesson);
  bad.quiz[0]!.evidence = [];
  const { result, text } = await call(tools, 'emit_lesson', bad);
  assert.equal(result.isError, true);
  assert.match(text, /evidence/);
});

test('emit_trace 拒绝没有 steps 的轨迹', async () => {
  const slot = createEmitSlot();
  const tools = createEmitTools(slot);
  const { result } = await call(tools, 'emit_trace', { key: 't1', title: 'x', steps: [] });
  assert.equal(result.isError, true);
});

test('emit_trace 接受带 certainty 的轨迹', async () => {
  const slot = createEmitSlot();
  const tools = createEmitTools(slot);
  const { payload } = await call(tools, 'emit_trace', {
    key: 't1',
    title: '主链路',
    steps: [
      {
        index: 0,
        title: '接收请求',
        certainty: 'source_fact',
        evidence: [{ file: 'pkg/mod.py', line_start: 1, line_end: 1, symbol: 'alpha' }],
        variables: [{ name: 'message', value: 'hi', note: '示例值' }],
      },
    ],
  });
  assert.equal(payload.accepted, true);
  assert.ok(slot.traces.t1);
});

test('schemaJson 可导出且不含 $ref 引用', () => {
  const js = schemaJson('lesson');
  assert.ok(js);
  const text = JSON.stringify(js);
  assert.equal(text.includes('"$ref"'), false);
  assert.equal(schemaJson('nope'), null);
});
