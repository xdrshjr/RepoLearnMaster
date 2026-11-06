/**
 * Pure reducer for P02 (course preparation) so the SSE wiring stays testable.
 *
 * The four sections on the prepare page mirror the four chapters of the course
 * (宏观架构 / 全局走读 / 深入源码 / 完成与书籍). The backend names workflow nodes
 * `N1..N9` (spec §3.4); we map those, and fall back to progress quartiles when a
 * node name is something we have never seen — a new node must light *something*
 * rather than freeze the UI at 0%.
 */

import type { EnvelopeEvent } from '@/lib/sse/parse';

export const PREPARE_SECTIONS = [
  { key: 'macro', title: '宏观架构', description: '解析仓库、抽取知识图谱、规划章节骨架' },
  { key: 'walkthrough', title: '全局走读', description: '生成调用链与走读脚本、板书动作' },
  { key: 'deep_dive', title: '深入源码', description: '逐课时写讲解、校验锚点与代码注释' },
  { key: 'publish', title: '完成与书籍', description: '发布版本、合成音频、可选导出书籍' },
] as const;

export type SectionState = 'pending' | 'active' | 'done' | 'failed';

export interface PrepareState {
  sections: SectionState[];
  node: string | null;
  progress: number;
  message: string | null;
  warnings: Array<{ node: string; warnings: string[] }>;
  error: { code: string; message: string; retryable: boolean } | null;
  completed: boolean;
  lastSeq: number;
}

export const initialPrepareState: PrepareState = {
  sections: ['pending', 'pending', 'pending', 'pending'],
  node: null,
  progress: 0,
  message: null,
  warnings: [],
  error: null,
  completed: false,
  lastSeq: 0,
};

export function mapNodeToSection(node: string | null | undefined, progress = 0): number {
  if (!node) return progress > 0 ? Math.min(3, Math.floor(progress / 25)) : 0;
  const name = node.toLowerCase();

  // Explicit LangGraph node names first.
  const numeric = /^n(\d+)/.exec(name);
  if (numeric) {
    const index = Number.parseInt(numeric[1] ?? '1', 10);
    if (index <= 4) return 0;
    if (index === 5) return 1;
    if (index <= 8) return 2;
    return 3;
  }

  if (/ingest|clone|resolve|analyz|knowledge|graph/.test(name)) return 0;
  if (/curriculum|plan|outline|chapter|blueprint|trace|walkthrough/.test(name)) return 1;
  if (/lesson|write|critic|verify|anchor|quiz|narration|board/.test(name)) return 2;
  if (/publish|audio|tts|book|validat|final|reap/.test(name)) return 3;
  return Math.min(3, Math.floor(progress / 25));
}

/**
 * Applies one SSE envelope. Unknown types return the previous state untouched
 * (the hook already logged them), so the page never blanks out.
 */
export function reducePrepareEvent(state: PrepareState, event: EnvelopeEvent): PrepareState {
  const data = event.data ?? {};

  switch (event.type) {
    case 'job.phase': {
      const node = typeof data.node === 'string' ? data.node : state.node;
      const progressValue = Number(data.progress ?? state.progress);
      const progress = Number.isFinite(progressValue) ? Math.min(100, Math.max(0, progressValue)) : state.progress;
      const target = mapNodeToSection(node, progress);
      const sections = state.sections.map((value, index) => {
        if (index < target) return value === 'failed' ? value : 'done';
        if (index === target) return 'active';
        return value === 'done' ? 'done' : 'pending';
      });
      const phase = typeof data.phase === 'string' ? ` · ${data.phase}` : '';
      return {
        ...state,
        node,
        progress,
        sections,
        message: `${node ?? '生成中'}${phase}`,
        lastSeq: event.seq || state.lastSeq,
      };
    }

    case 'node.completed': {
      const node = typeof data.node === 'string' ? data.node : '';
      const target = mapNodeToSection(node, state.progress);
      const sections = state.sections.map((value, index) =>
        index <= target && value !== 'failed' ? 'done' : value,
      );
      const rawWarnings = Array.isArray(data.warnings) ? data.warnings : [];
      const warnings = rawWarnings
        .map((warning) => (typeof warning === 'string' ? warning : JSON.stringify(warning)))
        .filter((warning) => warning.length > 0);
      return {
        ...state,
        sections,
        warnings: warnings.length > 0 ? [...state.warnings, { node: node || 'node', warnings }] : state.warnings,
        lastSeq: event.seq || state.lastSeq,
      };
    }

    case 'job.completed': {
      return {
        ...state,
        sections: state.sections.map((value) => (value === 'failed' ? value : 'done')),
        progress: 100,
        completed: true,
        message: '课程已发布',
        lastSeq: event.seq || state.lastSeq,
      };
    }

    case 'job.failed': {
      const code = typeof data.code === 'string' ? data.code : 'INTERNAL';
      const message = typeof data.message === 'string' ? data.message : '生成失败';
      return {
        ...state,
        sections: state.sections.map((value) => (value === 'pending' ? 'pending' : value)),
        error: { code, message, retryable: data.retryable !== false },
        lastSeq: event.seq || state.lastSeq,
      };
    }

    case 'budget.exceeded': {
      const kind = typeof data.kind === 'string' ? data.kind : 'tokens';
      const used = Number(data.used ?? 0);
      const limit = Number(data.limit ?? 0);
      const warning = `预算触顶（${kind}）：${used} / ${limit}。已生成的课时仍然可学。`;
      return { ...state, warnings: [...state.warnings, { node: 'budget', warnings: [warning] }] };
    }

    default:
      return state;
  }
}

/** `GET /api/jobs/{id}` snapshot → same shape, used after `job.snapshot`. */
export function stateFromJobSnapshot(
  state: PrepareState,
  snapshot: { status?: string; progress?: number; node?: string | null; message?: string | null; error?: Record<string, unknown> | null },
): PrepareState {
  const progress = Number(snapshot.progress ?? state.progress);
  const target = mapNodeToSection(snapshot.node ?? state.node, Number.isFinite(progress) ? progress : 0);
  const completed = snapshot.status === 'succeeded' || snapshot.status === 'done' || snapshot.status === 'ready';
  const failed = snapshot.status === 'failed' || snapshot.status === 'failed_budget';
  const sections = state.sections.map((value, index) => {
    if (completed) return 'done';
    if (index < target) return 'done';
    if (index === target) return failed ? 'failed' : 'active';
    return value === 'done' ? 'done' : 'pending';
  });
  return {
    ...state,
    sections,
    node: snapshot.node ?? state.node,
    progress: Number.isFinite(progress) ? progress : state.progress,
    message: snapshot.message ?? state.message,
    completed: completed || state.completed,
    error: failed
      ? {
          code: typeof snapshot.error?.code === 'string' ? snapshot.error.code : 'INTERNAL',
          message: typeof snapshot.error?.message === 'string' ? snapshot.error.message : '生成失败',
          retryable: snapshot.error?.retryable !== false,
        }
      : state.error,
  };
}
