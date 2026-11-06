import { describe, expect, it } from 'vitest';

import {
  buildDecorations,
  notesByLine,
  selectionRange,
  splitLines,
  toLineStates,
} from '@/lib/ide/decorations';

const FILE = 'autogen/agentchat/agent.py';
const OTHER = 'autogen/oai/client.py';

describe('decoration ranges', () => {
  const decorations = buildDecorations({
    file: FILE,
    focus: { file: FILE, lineStart: 99, lineEnd: 100 },
    codeNotes: [
      { file: FILE, line: 99, text: '把 messages 规范化成模型输入' },
      { file: OTHER, line: 5, text: '别的文件，不该出现' },
    ],
    evidence: [{ file: FILE, line_start: 101, line_end: 101, symbol: 'build_prompt' }],
    lineCount: 412,
  });

  it('keeps only decorations for the open file', () => {
    expect(decorations.filter((item) => item.kind === 'note')).toHaveLength(1);
    expect(decorations.every((item) => item.lineStart >= 1 && item.lineEnd <= 412)).toBe(true);
  });

  it('flags focus lines with the accent bar state', () => {
    const states = toLineStates(decorations, 412);
    expect(states[98]?.isFocus).toBe(true);
    expect(states[99]?.isFocus).toBe(true);
    expect(states[100]?.isFocus).toBe(false);
    // the evidence line is underlined, not focused
    expect(states[100]?.isEvidence).toBe(true);
  });

  it('collects note text per line for the line-end icon', () => {
    const states = toLineStates(decorations, 412);
    expect(states[98]?.notes[0]).toContain('messages');
    const map = notesByLine([{ file: FILE, line: 7, text: 'hi' }], FILE);
    expect(map.get(7)).toBe('hi');
    expect(map.get(8)).toBeUndefined();
  });

  it('clamps out-of-range lines instead of throwing', () => {
    const clamped = buildDecorations({
      file: FILE,
      focus: { file: FILE, lineStart: 0, lineEnd: 99_999 },
      codeNotes: [],
      evidence: [],
      lineCount: 50,
    });
    expect(clamped[0]?.lineStart).toBe(1);
    expect(clamped[0]?.lineEnd).toBe(50);
  });

  it('returns no decorations when nothing matches the file', () => {
    const empty = buildDecorations({
      file: FILE,
      focus: { file: OTHER, lineStart: 3, lineEnd: 4 },
      codeNotes: [],
      evidence: [],
      lineCount: 20,
    });
    expect(empty).toHaveLength(0);
  });
});

describe('fallback pane helpers', () => {
  it('splits content into lines and ignores CRLF', () => {
    expect(splitLines('a\r\nb\nc')).toEqual(['a', 'b', 'c']);
    expect(splitLines('')).toEqual([]);
  });

  it('maps a text selection to a line range', () => {
    const content = 'line1\nline2\nline3';
    const start = content.indexOf('line2');
    const end = content.length;
    const range = selectionRange(content, start, end);
    expect(range?.lineStart).toBe(2);
    expect(range?.lineEnd).toBe(3);
    expect(range?.text).toContain('line3');
  });

  it('returns null for an empty selection', () => {
    expect(selectionRange('abc', 1, 1)).toBeNull();
  });
});
