'use client';

import { Fragment, type ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * Responsive table — spec §3.3.1 / §3.3.2 D31.
 *
 * At `≥md` this is a plain `<table>`. Below `md` a wide table is the single most
 * reliable way to create horizontal scrolling (five columns × 11px text cannot
 * fit 390px), so the same data is rendered as a `<dl>`: every field keeps a `<dt>`
 * label, which is what makes the card form readable to a screen reader — a bare
 * `<div>` grid would be visually fine and semantically empty.
 *
 * Both forms are rendered and toggled with CSS (`md:hidden` / `hidden md:block`):
 * `display: none` removes the hidden copy from the accessibility tree, so there is
 * no duplicate reading, and no JS media query is needed for a static decision.
 */

export interface TableColumn<T> {
  /** Stable key (also used to keep the `<dt>` order predictable). */
  key: string;
  /** Header cell content for the `≥md` table. */
  header: ReactNode;
  /** `<dt>` label in the card form. Falls back to `header` when it is a string. */
  label?: string;
  cell: (row: T) => ReactNode;
  /** Extra classes for `<td>`. */
  className?: string;
  /** Extra classes for `<th>`. */
  headerClassName?: string;
}

export interface TableProps<T> {
  columns: Array<TableColumn<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  /** Accessible name of the table (rendered as a visually hidden `<caption>`). */
  caption: string;
  /**
   * `true` (default): `<md` renders a `<dl>` card list. Set `false` for tables that
   * already fit (they keep the `<table>` at every width instead of silently
   * changing shape on small screens).
   */
  responsive?: boolean;
  empty?: ReactNode;
  className?: string;
}

function labelOf<T>(column: TableColumn<T>): string {
  if (column.label) return column.label;
  return typeof column.header === 'string' ? column.header : column.key;
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  caption,
  responsive = true,
  empty,
  className,
}: TableProps<T>) {
  if (rows.length === 0) {
    return <>{empty ?? <p className="p-3 text-[11px] text-text-dim">暂无数据。</p>}</>;
  }

  return (
    <>
      <div
        className={cn(
          'rl-scroll-x rounded-[var(--radius-sm)] border border-border',
          responsive && 'hidden md:block',
          className,
        )}
      >
        <table className="w-full border-collapse text-[11px]">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="bg-surface-2 text-left text-[10px] text-text-dim">
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={cn('px-2 py-1.5 font-medium', column.headerClassName)}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={rowKey(row)} className="border-t border-border">
                {columns.map((column) => (
                  <td key={column.key} className={cn('px-2 py-1.5 align-top', column.className)}>
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {responsive ? (
        <div role="group" aria-label={caption} className="space-y-2 md:hidden">
          <dl className="space-y-2">
            {rows.map((row) => (
              <div
                key={rowKey(row)}
                className="grid grid-cols-[minmax(0,6.5rem)_minmax(0,1fr)] items-start gap-x-2 gap-y-1 rounded-[var(--radius-sm)] border border-border bg-surface p-2"
              >
                {columns.map((column) => (
                  // dt/dd 必须是 `<dl>`（组内）的直接子元素，中间不能再套一层 div，
                  // 否则语义树里会多出一层"没有角色的容器"（`display: contents` 只
                  // 改视觉，不改语义）。
                  <Fragment key={column.key}>
                    <dt className="text-[10px] leading-[1.5] text-text-dim">{labelOf(column)}</dt>
                    <dd className="min-w-0 text-[11px] leading-[1.6] text-text">
                      {column.cell(row)}
                    </dd>
                  </Fragment>
                ))}
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </>
  );
}
