'use client';

import { Copy, GitFork, Lightbulb, Maximize2 } from 'lucide-react';
import { useState } from 'react';

import { Badge, Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/toast';
import type { Board, BoardNode } from '@/lib/api/types';
import { readNumber, readString } from '@/lib/api/types';
import { cn } from '@/lib/utils';

export interface AnchorJump {
  file: string;
  lineStart: number;
  lineEnd: number;
}

function nodeTarget(node: BoardNode): AnchorJump | null {
  const source = node.source;
  if (!source) return null;
  const file = readString(source, 'file');
  if (!file) return null;
  const lineStart = readNumber(source, 'line', readNumber(source, 'line_start', 1));
  const lineEnd = readNumber(source, 'line_end', lineStart);
  return { file, lineStart, lineEnd };
}

/**
 * Architecture canvas — spec §7.2 第一层.
 *
 * The spec calls for "mermaid + clickable nodes". We do not ship a mermaid
 * renderer (no dependency allowed), so the canvas renders the node graph from
 * `board.nodes` as large clickable cards and keeps the mermaid source one click
 * away (`board.mermaid`) — clicking a node jumps the code pane to its anchor.
 */
export function ArchitectureCanvas({
  board,
  onJump,
}: {
  board: Board | null;
  onJump: (target: AnchorJump) => void;
}) {
  const toast = useToast();
  const [showSource, setShowSource] = useState(false);

  if (!board || (board.nodes.length === 0 && !board.mermaid)) {
    return (
      <Card className="text-[11px] text-text-dim">
        本节没有架构板。可以直接在右侧读代码，或切到“全局走读”看调用链。
      </Card>
    );
  }

  return (
    <Card className="space-y-3">
      <div className="flex items-center gap-2">
        <GitFork className="size-3.5 text-accent" aria-hidden />
        <h3 className="text-xs font-semibold text-text">架构画布</h3>
        <Badge tone="muted">{board.kind}</Badge>
        <span className="ml-auto text-[10px] text-text-dim">点击节点跳到对应源码</span>
        {board.mermaid ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowSource((value) => !value)}
            icon={<Maximize2 className="size-3" aria-hidden />}
          >
            {showSource ? '收起 Mermaid' : '查看 Mermaid'}
          </Button>
        ) : null}
      </div>

      {board.nodes.length > 0 ? (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {board.nodes.map((node) => {
            const target = nodeTarget(node);
            return (
              <button
                key={node.id}
                type="button"
                onClick={() => {
                  if (target) onJump(target);
                  else
                    toast.push({
                      tone: 'info',
                      title: '这个节点没有源码锚点',
                      description: '它属于概念层（例如“用户请求”），在讲解里会给出对应文件。',
                    });
                }}
                className={cn(
                  'group flex flex-col gap-1 rounded-[var(--radius-sm)] border border-border bg-surface-2/50 p-2.5 text-left transition-colors',
                  'hover:border-accent/60 hover:bg-accent-soft',
                )}
              >
                <span className="flex items-center gap-1.5">
                  <span aria-hidden className="size-1.5 rounded-full bg-accent" />
                  <span className="truncate text-xs text-text">{node.label}</span>
                </span>
                <span className="truncate font-mono text-[10px] text-text-dim">
                  {target ? `${target.file}:${target.lineStart}` : '无锚点 · 概念节点'}
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <p className="text-[11px] text-text-dim">没有可点击的节点，改用下面的 Mermaid 源码理解结构。</p>
      )}

      {showSource && board.mermaid ? (
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-text-dim">Mermaid 源码（便于复制到别处渲染）</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                void navigator.clipboard?.writeText(board.mermaid);
                toast.push({ tone: 'success', title: '已复制 Mermaid 源码' });
              }}
              icon={<Copy className="size-3" aria-hidden />}
            >
              复制
            </Button>
          </div>
          <pre className="max-h-56 overflow-auto rounded-[var(--radius-sm)] border border-border bg-code-bg p-2 font-mono text-[11px] leading-[1.55] text-text-muted">
            {board.mermaid}
          </pre>
        </div>
      ) : null}
    </Card>
  );
}

export function ConceptCard({
  concept,
  onJump,
}: {
  concept: {
    title: string;
    body: string;
    evidence?: Array<{ file: string; line_start: number; line_end: number; symbol?: string }>;
  };
  onJump?: (target: AnchorJump) => void;
}) {
  return (
    <Card className="space-y-2">
      <div className="flex items-center gap-1.5">
        <Lightbulb className="size-3.5 text-warn" aria-hidden />
        <h3 className="text-xs font-semibold text-text">{concept.title}</h3>
      </div>
      <p className="text-[12px] leading-[1.65] text-text-muted">{concept.body}</p>
      {concept.evidence && concept.evidence.length > 0 ? (
        <ul className="space-y-1 border-t border-border pt-2">
          {concept.evidence.map((evidence, index) => (
            <li key={`${evidence.file}-${index}`}>
              <button
                type="button"
                onClick={() =>
                  onJump?.({
                    file: evidence.file,
                    lineStart: evidence.line_start,
                    lineEnd: evidence.line_end,
                  })
                }
                className="font-mono text-[10px] text-info underline decoration-dotted underline-offset-2 hover:text-accent"
              >
                {evidence.file}:{evidence.line_start}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}
