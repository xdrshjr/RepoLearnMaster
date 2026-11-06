/**
 * 课程产出物的 zod schema（spec §4.2 `src/contracts/schema.ts`）。
 *
 * **一处定义、两侧校验**是本方案防止"模型输出漂移"的核心机制：这里用 zod 定义
 * 形状 → `zod-to-json-schema` 导出 JSON Schema → Python 侧用同一份 schema 做
 * 二次校验（`tests/test_contracts.py`）。所以这些 schema 是**契约**而不是
 * "顺手写的校验"，任何字段改动都等于改契约。
 *
 * 注意：字段全部 `optional` 到"能表达意图"为止，不做过度约束。过严的 schema 在
 * 真实模型上会持续返回校验错误，最终被放宽成恒真——这比不校验更糟。
 */

import { z } from 'zod';

export const AnchorRefSchema = z.object({
  file: z.string().min(1),
  symbol: z.string().optional(),
  line_start: z.number().int().min(1),
  line_end: z.number().int().min(1),
  kind: z.enum(['definition', 'call_site', 'config', 'test']).default('definition'),
});

export const LessonPlanSchema = z.object({
  key: z.string().min(1),
  title: z.string().min(1).max(120),
  goal: z.string().min(1).max(600),
  minutes: z.number().int().min(1).max(30).default(6),
  anchors: z.array(AnchorRefSchema).default([]),
});

export const SectionPlanSchema = z.object({
  key: z.enum(['overview', 'walkthrough', 'deep_dive', 'recap']),
  title: z.string().min(1).max(120),
  minutes: z.number().int().min(1).max(120).default(5),
  lessons: z.array(LessonPlanSchema).min(1),
});

export const CurriculumSchema = z.object({
  title: z.string().min(1).max(160),
  subtitle: z.string().max(300).optional(),
  summary_md: z.string().max(4000).optional(),
  chain_id: z.string().optional(),
  sections: z.array(SectionPlanSchema).min(1),
});

export const SegmentSchema = z.object({
  id: z.string().min(1),
  text: z.string().min(1),
  start_ms: z.number().int().min(0),
  end_ms: z.number().int().min(0),
  focus: AnchorRefSchema.pick({ file: true, line_start: true, line_end: true }).optional(),
  board_actions: z.array(z.record(z.string(), z.unknown())).optional(),
  subtitle_style: z.enum(['normal', 'emphasis', 'aside']).optional(),
});

export const BoardNodeSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  source: z.object({ file: z.string(), line: z.number().int().min(1) }).optional(),
});

export const BoardSchema = z.object({
  kind: z.enum(['architecture', 'flow']),
  mermaid: z.string().min(1),
  nodes: z.array(BoardNodeSchema).default([]),
});

export const CodeNoteSchema = z.object({
  file: z.string().min(1),
  line: z.number().int().min(1),
  text: z.string().min(1).max(600),
});

export const QuizItemSchema = z.object({
  id: z.string().min(1),
  stem: z.string().min(1).max(600),
  choices: z
    .array(z.object({ id: z.string().min(1), text: z.string().min(1).max(300) }))
    .min(2)
    .max(6),
  answer_id: z.string().min(1),
  explanation_md: z.string().min(1).max(2000),
  evidence: z.array(AnchorRefSchema).min(1),
  difficulty: z.number().int().min(1).max(3).default(1),
  kind: z.enum(['prediction', 'recall', 'trace']).default('recall'),
});

export const LessonSchema = z.object({
  key: z.string().min(1),
  title: z.string().min(1).max(160),
  layer: z.enum(['overview', 'walkthrough', 'deep_dive', 'recap']),
  minutes: z.number().int().min(1).max(40).default(6),
  goal: z.string().max(600).optional(),
  steps: z
    .array(
      z.object({
        index: z.number().int().min(0),
        title: z.string().min(1).max(160),
        duration_ms: z.number().int().min(1000).max(1_800_000),
        timing_source: z.enum(['tts', 'estimated']).default('estimated'),
        segments: z.array(SegmentSchema).min(1),
        board: BoardSchema.optional(),
        code_notes: z.array(CodeNoteSchema).optional(),
      }),
    )
    .min(1),
  files: z.array(z.object({ path: z.string(), lang: z.string().optional() })).default([]),
  trace_key: z.string().optional(),
  quiz: z.array(QuizItemSchema).default([]),
});

export const TraceStepSchema = z.object({
  index: z.number().int().min(0),
  title: z.string().min(1).max(160),
  certainty: z.enum(['source_fact', 'static_inference', 'teaching_simulation']),
  detail: z.string().max(1200).optional(),
  evidence: z.array(AnchorRefSchema).default([]),
  variables: z
    .array(
      z.object({
        name: z.string().min(1),
        value: z.string(),
        note: z.string().optional(),
      }),
    )
    .default([]),
});

export const TraceSchema = z.object({
  key: z.string().min(1),
  title: z.string().min(1).max(160),
  entry: AnchorRefSchema.optional(),
  steps: z.array(TraceStepSchema).min(1),
});

export const BookChapterSchema = z.object({
  key: z.string().min(1),
  title: z.string().min(1).max(160),
  blocks: z
    .array(
      z.object({
        type: z.enum(['md', 'code', 'figure', 'table']),
        text: z.string().optional(),
        lang: z.string().optional(),
        caption: z.string().optional(),
      }),
    )
    .min(1),
  source_refs: z.array(AnchorRefSchema).default([]),
});

export const NamedSchema = {
  curriculum: CurriculumSchema,
  lesson: LessonSchema,
  trace: TraceSchema,
  quiz: QuizItemSchema,
  book_chapter: BookChapterSchema,
} as const;

export type NamedSchemaName = keyof typeof NamedSchema;

export function getSchema(name: string) {
  const s = NamedSchema[name as NamedSchemaName];
  return s ?? null;
}
