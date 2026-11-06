'use client';

import { MessageSquarePlus, Sparkles, Waypoints } from 'lucide-react';

import { ASK_ACTIONS, type AskActionId } from '@/lib/ide/decorations';
import type { LineSelection } from '@/stores/ide';

const ICONS: Record<AskActionId, typeof Sparkles> = {
  explain: Sparkles,
  why: Waypoints,
  alternatives: MessageSquarePlus,
};

/**
 * Floating selection toolbar — spec §7.2 行内提问.
 *
 * Rendered in a portal-free fixed layer (the code pane has `overflow: auto`,
 * which would clip an absolutely positioned child) anchored to the selection
 * rect when the renderer can provide one.
 */
export function SelectionToolbar({
  selection,
  anchor,
  onAsk,
  onDismiss,
  busy,
}: {
  selection: LineSelection;
  anchor: { top: number; left: number } | null;
  onAsk: (actionId: AskActionId) => void;
  onDismiss: () => void;
  busy?: boolean;
}) {
  const position = anchor ?? { top: 96, left: 320 };
  return (
    <div
      role="toolbar"
      aria-label="对选中的代码提问"
      className="fixed z-40 flex items-center gap-1 rounded-[var(--radius)] border border-border-strong bg-surface p-1 shadow-[var(--shadow-soft)]"
      style={{ top: Math.max(8, position.top), left: Math.max(8, position.left) }}
    >
      <span className="px-2 text-[11px] text-text-dim">
        {selection.lineStart === selection.lineEnd
          ? `第 ${selection.lineStart} 行`
          : `${selection.lineStart}–${selection.lineEnd} 行`}
      </span>
      {ASK_ACTIONS.map((action) => {
        const Icon = ICONS[action.id];
        return (
          <button
            key={action.id}
            type="button"
            disabled={busy}
            onClick={() => onAsk(action.id)}
            className="inline-flex items-center gap-1 rounded-[var(--radius-sm)] px-2 py-1.5 text-[11px] text-text-muted transition-colors hover:bg-accent-soft hover:text-accent disabled:opacity-50"
          >
            <Icon className="size-3" aria-hidden />
            {action.label}
          </button>
        );
      })}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="收起工具条"
        className="rounded-[var(--radius-sm)] px-1.5 py-1 text-[11px] text-text-dim hover:text-text"
      >
        ✕
      </button>
    </div>
  );
}
