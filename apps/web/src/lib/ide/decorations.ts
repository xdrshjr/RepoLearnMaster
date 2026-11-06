/**
 * Read-only IDE decoration math — spec §7.4.
 *
 * Pure functions so the same ranges drive both renderers:
 *  - Monaco `deltaDecorations` (the real editor);
 *  - the DOM fallback pane (used when the Monaco CDN is unreachable, which is a
 *    real possibility on an offline dev box — a blank code pane would be worse
 *    than a plain one).
 */

import type { CodeNote, EvidenceView } from '@/lib/api/types';

export type DecorationKind = 'focus' | 'note' | 'evidence';

export interface LineDecoration {
  kind: DecorationKind;
  lineStart: number;
  lineEnd: number;
  /** Set for `note` decorations. */
  note?: string;
  /** Set for `evidence` decorations. */
  label?: string;
}

export interface LineState {
  isFocus: boolean;
  isEvidence: boolean;
  notes: string[];
}

export interface DecorationInput {
  file: string;
  focus: { file: string; lineStart: number; lineEnd: number } | null;
  codeNotes: CodeNote[];
  evidence: EvidenceView[];
  lineCount: number;
}

function clampLine(line: number, lineCount: number): number {
  if (!Number.isFinite(line)) return 1;
  return Math.min(Math.max(Math.round(line), 1), Math.max(1, lineCount));
}

export function buildDecorations({
  file,
  focus,
  codeNotes,
  evidence,
  lineCount,
}: DecorationInput): LineDecoration[] {
  const decorations: LineDecoration[] = [];

  if (focus && focus.file === file) {
    decorations.push({
      kind: 'focus',
      lineStart: clampLine(focus.lineStart, lineCount),
      lineEnd: clampLine(focus.lineEnd, lineCount),
    });
  }

  for (const note of codeNotes ?? []) {
    if (note.file !== file) continue;
    decorations.push({
      kind: 'note',
      lineStart: clampLine(note.line, lineCount),
      lineEnd: clampLine(note.line, lineCount),
      note: note.text,
    });
  }

  for (const item of evidence ?? []) {
    if (item.file !== file) continue;
    decorations.push({
      kind: 'evidence',
      lineStart: clampLine(item.line_start, lineCount),
      lineEnd: clampLine(item.line_end, lineCount),
      label: item.symbol ?? item.note,
    });
  }

  return decorations;
}

/** Per-line flags, 0-indexed by line number - 1. */
export function toLineStates(decorations: LineDecoration[], lineCount: number): LineState[] {
  const states: LineState[] = Array.from({ length: Math.max(1, lineCount) }, () => ({
    isFocus: false,
    isEvidence: false,
    notes: [],
  }));

  for (const decoration of decorations) {
    const start = Math.max(1, decoration.lineStart);
    const end = Math.min(states.length, decoration.lineEnd);
    for (let line = start; line <= end; line += 1) {
      const state = states[line - 1];
      if (!state) continue;
      if (decoration.kind === 'focus') state.isFocus = true;
      if (decoration.kind === 'evidence') state.isEvidence = true;
      if (decoration.kind === 'note' && decoration.note) state.notes.push(decoration.note);
    }
  }

  return states;
}

/** Notes keyed by line, for the fallback renderer's line-end icons. */
export function notesByLine(codeNotes: CodeNote[], file: string): Map<number, string> {
  const map = new Map<number, string>();
  for (const note of codeNotes ?? []) {
    if (note.file !== file) continue;
    map.set(note.line, note.text);
  }
  return map;
}

export function splitLines(content: string): string[] {
  if (!content) return [];
  return content.replace(/\r\n/g, '\n').split('\n');
}

/**
 * The line range implied by a text selection inside the fallback pane. Kept
 * separate from the DOM so the behaviour is testable.
 */
export function selectionRange(
  content: string,
  selectionStart: number,
  selectionEnd: number,
): { lineStart: number; lineEnd: number; text: string } | null {
  if (selectionEnd <= selectionStart) return null;
  const before = content.slice(0, selectionStart);
  const selected = content.slice(selectionStart, selectionEnd);
  const lineStart = before.split('\n').length;
  const lineEnd = lineStart + (selected.match(/\n/g)?.length ?? 0);
  return { lineStart, lineEnd, text: selected };
}

export const ASK_ACTIONS = [
  { id: 'explain', label: '解释这行', question: '用一句话解释这段代码在做什么，并指出它在调用链里的位置。' },
  {
    id: 'why',
    label: '为什么这样实现？',
    question: '为什么这里要这样实现？如果换成更直白的写法，会失去什么？',
  },
  {
    id: 'alternatives',
    label: '有什么替代方案',
    question: '这段代码有哪些常见的替代实现方案？各自在性能、可读性、可维护性上有什么取舍？',
  },
] as const;

export type AskActionId = (typeof ASK_ACTIONS)[number]['id'];
