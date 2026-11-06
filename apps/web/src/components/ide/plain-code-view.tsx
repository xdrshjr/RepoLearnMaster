'use client';

import { useMemo, useState } from 'react';

import type { LineDecoration } from '@/lib/ide/decorations';
import { notesByLine, splitLines, toLineStates } from '@/lib/ide/decorations';
import { cn } from '@/lib/utils';

export interface PlainCodeViewProps {
  content: string;
  decorations: LineDecoration[];
  fontSize: number;
  focusLine: number | null;
  onSelect: (selection: { lineStart: number; lineEnd: number; text: string }, rect: DOMRect | null) => void;
  onNoteClick: (line: number) => void;
}

/**
 * DOM fallback for the read-only IDE.
 *
 * Same decoration semantics as Monaco (focus tint + 3px accent bar, note icon at
 * line end, wavy underline for trace evidence) so the deep-dive page keeps every
 * affordance when the Monaco AMD loader cannot be reached.
 */
export function PlainCodeView({
  content,
  decorations,
  fontSize,
  focusLine,
  onSelect,
  onNoteClick,
}: PlainCodeViewProps) {
  const [selectedLines, setSelectedLines] = useState<{ start: number; end: number } | null>(null);
  const lines = useMemo(() => splitLines(content), [content]);
  const states = useMemo(() => toLineStates(decorations, lines.length), [decorations, lines.length]);
  const noteMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const decoration of decorations) {
      if (decoration.kind === 'note' && decoration.note) map.set(decoration.lineStart, decoration.note);
    }
    return map;
  }, [decorations]);

  const handleMouseUp = () => {
    const selection = typeof window !== 'undefined' ? window.getSelection() : null;
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
      setSelectedLines(null);
      onSelect({ lineStart: 0, lineEnd: 0, text: '' }, null);
      return;
    }
    const range = selection.getRangeAt(0);
    const root = range.startContainer;
    const lineOf = (node: Node): number | null => {
      const element =
        node.nodeType === Node.ELEMENT_NODE ? (node as HTMLElement) : node.parentElement;
      const lineEl = element?.closest('[data-line]');
      const raw = lineEl?.getAttribute('data-line');
      return raw ? Number.parseInt(raw, 10) : null;
    };
    const start = lineOf(root);
    const end = lineOf(range.endContainer) ?? start;
    if (start == null || end == null) return;
    const rect = range.getBoundingClientRect();
    setSelectedLines({ start, end });
    onSelect({ lineStart: Math.min(start, end), lineEnd: Math.max(start, end), text: selection.toString() }, rect);
  };

  if (lines.length === 0) {
    return <p className="p-4 text-xs text-text-dim">文件内容为空。</p>;
  }

  return (
    <div
      className="h-full overflow-auto font-mono leading-[1.55] rl-scroll-thin"
      style={{ fontSize: `${fontSize}px` }}
      onMouseUp={handleMouseUp}
      data-testid="plain-code-view"
    >
      {lines.map((line, index) => {
        const lineNumber = index + 1;
        const state = states[index];
        const note = noteMap.get(lineNumber) ?? state?.notes[0];
        const isSelected =
          selectedLines && lineNumber >= selectedLines.start && lineNumber <= selectedLines.end;
        return (
          <div
            key={lineNumber}
            data-line={lineNumber}
            className={cn(
              'group flex items-start gap-3 px-2',
              state?.isFocus && 'bg-[var(--code-line-hl)] shadow-[inset_3px_0_0_0_var(--accent)]',
              isSelected && 'bg-accent/10',
              focusLine === lineNumber && 'outline outline-1 outline-accent/40',
            )}
          >
            <span
              aria-hidden
              className="w-10 shrink-0 select-none pr-2 text-right text-text-dim/70"
            >
              {lineNumber}
            </span>
            <span
              className={cn(
                'min-w-0 flex-1 whitespace-pre-wrap break-words text-text',
                state?.isEvidence && 'underline decoration-info decoration-wavy underline-offset-4',
              )}
            >
              {line || ' '}
            </span>
            {note ? (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onNoteClick(lineNumber);
                }}
                title={note}
                aria-label={`第 ${lineNumber} 行的代码注释：${note}`}
                className="mt-0.5 shrink-0 rounded px-1 text-[11px] text-accent opacity-70 transition-opacity hover:opacity-100"
              >
                ●
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
