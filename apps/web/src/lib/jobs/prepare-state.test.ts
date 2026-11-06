import { describe, expect, it } from 'vitest';

import type { EnvelopeEvent } from '@/lib/sse/parse';
import {
  initialPrepareState,
  mapNodeToSection,
  reducePrepareEvent,
  stateFromJobSnapshot,
  type PrepareState,
} from '@/lib/jobs/prepare-state';

function event(type: string, data: Record<string, unknown> = {}, seq = 1): EnvelopeEvent {
  return { type, seq, ts: Date.now(), schemaVersion: 1, data };
}

describe('node → section mapping', () => {
  it('maps the LangGraph node names of spec §3.4', () => {
    expect(mapNodeToSection('N1_ingest')).toBe(0);
    expect(mapNodeToSection('N4_analyze_repo')).toBe(0);
    expect(mapNodeToSection('N5_curriculum')).toBe(1);
    expect(mapNodeToSection('N6_write_lesson')).toBe(2);
    expect(mapNodeToSection('N8_critic')).toBe(2);
    expect(mapNodeToSection('N9_publish')).toBe(3);
  });

  it('maps by keyword for human-readable node names', () => {
    expect(mapNodeToSection('clone-repo')).toBe(0);
    expect(mapNodeToSection('plan-chapters')).toBe(1);
    expect(mapNodeToSection('write-lesson')).toBe(2);
    expect(mapNodeToSection('synthesize-audio')).toBe(3);
  });

  it('falls back to progress quartiles for unknown nodes', () => {
    expect(mapNodeToSection('mystery-node', 10)).toBe(0);
    expect(mapNodeToSection('mystery-node', 30)).toBe(1);
    expect(mapNodeToSection('mystery-node', 55)).toBe(2);
    expect(mapNodeToSection('mystery-node', 90)).toBe(3);
  });
});

describe('prepare event reducer', () => {
  it('lights the current section and keeps earlier ones done', () => {
    let state: PrepareState = initialPrepareState;
    state = reducePrepareEvent(state, event('job.phase', { node: 'N1_ingest', progress: 5 }));
    expect(state.sections[0]).toBe('active');
    state = reducePrepareEvent(state, event('job.phase', { node: 'N6_write_lesson', progress: 60 }, 2));
    expect(state.sections[0]).toBe('done');
    expect(state.sections[1]).toBe('done');
    expect(state.sections[2]).toBe('active');
    expect(state.sections[3]).toBe('pending');
    expect(state.progress).toBe(60);
    expect(state.lastSeq).toBe(2);
  });

  it('records warnings from node.completed', () => {
    let state = reducePrepareEvent(initialPrepareState, event('job.phase', { node: 'N1', progress: 10 }));
    state = reducePrepareEvent(
      state,
      event('node.completed', { node: 'N1_ingest', warnings: ['INGEST_BLOCKED_PATH: ../etc/passwd'] }, 2),
    );
    expect(state.warnings).toHaveLength(1);
    expect(state.warnings[0]?.warnings[0]).toContain('INGEST_BLOCKED_PATH');
  });

  it('marks everything done on job.completed', () => {
    const state = reducePrepareEvent(
      reducePrepareEvent(initialPrepareState, event('job.phase', { node: 'N9', progress: 98 })),
      event('job.completed', { status: 'succeeded' }, 5),
    );
    expect(state.completed).toBe(true);
    expect(state.progress).toBe(100);
    expect(state.sections.every((value) => value === 'done')).toBe(true);
  });

  it('surfaces job.failed as retryable data, not a crash', () => {
    const state = reducePrepareEvent(
      initialPrepareState,
      event('job.failed', { code: 'PROVIDER_UNAVAILABLE', message: '超时', retryable: true }),
    );
    expect(state.error?.code).toBe('PROVIDER_UNAVAILABLE');
    expect(state.error?.retryable).toBe(true);
    expect(state.sections).toHaveLength(4);
  });

  it('ignores unknown event types (forward compatibility)', () => {
    const before = reducePrepareEvent(initialPrepareState, event('job.phase', { node: 'N1', progress: 5 }));
    const after = reducePrepareEvent(before, event('brand.new.event', { anything: true }, 9));
    expect(after).toBe(before);
  });

  it('adds a budget warning without failing the page', () => {
    const state = reducePrepareEvent(
      initialPrepareState,
      event('budget.exceeded', { kind: 'tokens', used: 180000, limit: 180000 }),
    );
    expect(state.warnings[0]?.warnings[0]).toContain('预算触顶');
    expect(state.error).toBeNull();
  });
});

describe('snapshot re-sync', () => {
  it('rebuilds state from GET /api/jobs/{id}', () => {
    const state = stateFromJobSnapshot(initialPrepareState, {
      status: 'running',
      progress: 45,
      node: 'N6_write_lesson',
      message: '写第 3 课时',
    });
    expect(state.sections[0]).toBe('done');
    expect(state.sections[2]).toBe('active');
    expect(state.message).toBe('写第 3 课时');
  });

  it('treats a failed snapshot as a failed section with an error', () => {
    const state = stateFromJobSnapshot(initialPrepareState, {
      status: 'failed',
      progress: 20,
      node: 'N1_ingest',
      error: { code: 'REPO_NOT_FOUND', message: '找不到仓库', retryable: false },
    });
    expect(state.error?.code).toBe('REPO_NOT_FOUND');
    expect(state.sections[0]).toBe('failed');
  });
});
