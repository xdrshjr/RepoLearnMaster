/**
 * 结构化产出工具（spec §3.5.2 `src/tools/emit.ts`）。
 *
 * 为什么强制 Agent 调用 `emit_*` 而不是"从自然语言里抠 JSON"：
 * 抠 JSON 的做法在真实模型上有三类必然失败——尾逗号、markdown 代码围栏、以及
 * 在 JSON 前后夹叙夹议。把"交付"变成一个**带 schema 的工具调用**之后，失败就
 * 从"解析失败"变成了"schema 校验失败"，而后者可以把**具体的校验错误回灌给模型**
 * 让它自己修（这是 self-repair 的唯一可靠形态）。
 */

import { defineTool } from '@aragon-agent/core';
import { zodToJsonSchema } from 'zod-to-json-schema';
import type { ZodTypeAny } from 'zod';

import { LessonSchema, TraceSchema, CurriculumSchema, QuizItemSchema } from '../contracts/schema.ts';
import { fail, ok } from './result.ts';

export interface EmitSlot {
  curriculum?: unknown;
  lessons: Record<string, unknown>;
  traces: Record<string, unknown>;
  quizzes: Record<string, unknown[]>;
  /** 每次 emit 的失败历史，便于事后看"模型为什么交不出东西"。 */
  failures: Array<{ tool: string; error: string }>;
  /**
   * 一次成功的 emit 之后回调。
   *
   * `emit_*` 是**交付通道**，交付完成就意味着这轮 run 的目的已经达到：模型之后
   * 再开一轮"总结一句"纯属浪费——每多一轮就要重发一遍整段上下文（实测单课时
   * 10 轮 × 15k ≈ 150k tokens，正好把节点 token 分闸撞掉，于是"已经写好的课时"
   * 被判超预算）。回调让 Kernel 在交付瞬间收工。
   */
  onDelivered?: (tool: string) => void;
}

export function createEmitSlot(): EmitSlot {
  return { lessons: {}, traces: {}, quizzes: {}, failures: [] };
}

function jsonSchemaOf(schema: ZodTypeAny): Record<string, unknown> {
  // `$refStrategy: 'none'` 让导出的 schema 自包含（Python 侧 jsonschema 不需要
  // 解析 `$defs` 的相对引用，减少一个失败点）。
  const js = zodToJsonSchema(schema as ZodTypeAny, { $refStrategy: 'none' }) as Record<string, unknown>;
  delete js.$schema;
  return js;
}

export function schemaJson(name: string): Record<string, unknown> | null {
  switch (name) {
    case 'curriculum':
      return jsonSchemaOf(CurriculumSchema);
    case 'lesson':
      return jsonSchemaOf(LessonSchema);
    case 'trace':
      return jsonSchemaOf(TraceSchema);
    case 'quiz':
      return jsonSchemaOf(QuizItemSchema);
    default:
      return null;
  }
}

function describeIssues(err: unknown): string {
  if (err && typeof err === 'object' && 'issues' in err) {
    const issues = (err as { issues: Array<{ path: Array<string | number>; message: string }> }).issues;
    return issues
      .slice(0, 8)
      .map((i) => `${i.path.join('.') || '<root>'}: ${i.message}`)
      .join('; ');
  }
  return (err as Error)?.message ?? String(err);
}

export function createEmitTools(slot: EmitSlot) {
  const emitCourseJson = defineTool({
    name: 'emit_course_json',
    label: '交付课程骨架',
    description:
      '交付整门课程的章节/课时骨架（4 个章节、10-12 个课时）。必须调用它才算完成任务；' +
      '校验失败时错误会返回给你，请修正后再次调用。不要用自然语言代替它。',
    parameters: jsonSchemaOf(CurriculumSchema),
    execute: async (_toolCallId: string, args: Record<string, unknown>) => {
      const parsed = CurriculumSchema.safeParse(args);
      if (!parsed.success) {
        const error = describeIssues(parsed.error);
        slot.failures.push({ tool: 'emit_course_json', error });
        return fail(error, { accepted: false });
      }
      slot.curriculum = parsed.data;
      slot.onDelivered?.('emit_course_json');
      return ok({ accepted: true, sections: parsed.data.sections.length });
    },
  });

  const emitLesson = defineTool({
    name: 'emit_lesson',
    label: '交付单个课时',
    description:
      '交付一个课时的完整内容（steps/segments/board/code_notes/quiz）。' +
      'segments 的 start_ms/end_ms 必须连续覆盖整段时长且不重叠。' +
      '校验失败时错误会返回给你，请修正后再次调用。',
    parameters: jsonSchemaOf(LessonSchema),
    execute: async (_toolCallId: string, args: Record<string, unknown>) => {
      const parsed = LessonSchema.safeParse(args);
      if (!parsed.success) {
        const error = describeIssues(parsed.error);
        slot.failures.push({ tool: 'emit_lesson', error });
        return fail(error, { accepted: false });
      }
      const key = parsed.data.key;
      slot.lessons[key] = parsed.data;
      slot.onDelivered?.('emit_lesson');
      if (parsed.data.quiz.length > 0) slot.quizzes[key] = parsed.data.quiz;
      return ok({ accepted: true, key, steps: parsed.data.steps.length });
    },
  });

  const emitTrace = defineTool({
    name: 'emit_trace',
    label: '交付执行轨迹',
    description:
      '交付一条模拟执行轨迹（每步带 certainty 与 evidence）。' +
      'certainty=source_fact 必须带 evidence（文件+行号+符号），否则发布前校验会失败。' +
      'certainty=teaching_simulation 的变量值必须带 note="示例值，非真实运行结果"。',
    parameters: jsonSchemaOf(TraceSchema),
    execute: async (_toolCallId: string, args: Record<string, unknown>) => {
      const parsed = TraceSchema.safeParse(args);
      if (!parsed.success) {
        const error = describeIssues(parsed.error);
        slot.failures.push({ tool: 'emit_trace', error });
        return fail(error, { accepted: false });
      }
      slot.traces[parsed.data.key] = parsed.data;
      slot.onDelivered?.('emit_trace');
      return ok({ accepted: true, key: parsed.data.key, steps: parsed.data.steps.length });
    },
  });

  return [emitCourseJson, emitLesson, emitTrace];
}
