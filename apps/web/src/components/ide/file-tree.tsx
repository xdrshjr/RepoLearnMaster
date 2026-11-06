'use client';

import { ChevronRight, FileCode2, Lock, Minus, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Badge } from '@/components/ui/card';
import type { FileRef } from '@/lib/api/types';
import { cn } from '@/lib/utils';

export function FileTree({
  files,
  activeFile,
  onOpen,
  className,
}: {
  files: FileRef[];
  activeFile: string | null;
  onOpen: (path: string) => void;
  className?: string;
}) {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return files;
    return files.filter((file) => file.path.toLowerCase().includes(keyword));
  }, [files, query]);

  return (
    <div className={cn('flex h-full min-h-0 flex-col border-r border-border bg-bg-elevated', className)}>
      <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
        <Search className="size-3 text-text-dim" aria-hidden />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="筛选文件"
          aria-label="筛选文件"
          className="w-full bg-transparent text-[11px] text-text placeholder:text-text-dim focus:outline-none"
        />
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto py-1 rl-scroll-thin">
        {filtered.length === 0 ? (
          <li className="px-3 py-2 text-[11px] text-text-dim">没有匹配的文件</li>
        ) : null}
        {filtered.map((file) => {
          const active = file.path === activeFile;
          const parts = file.path.split('/');
          const name = parts[parts.length - 1] ?? file.path;
          const dir = parts.slice(0, -1).join('/');
          return (
            <li key={file.path}>
              <button
                type="button"
                onClick={() => onOpen(file.path)}
                aria-current={active ? 'true' : undefined}
                className={cn(
                  'flex w-full items-start gap-1.5 px-2.5 py-1 text-left transition-colors',
                  active ? 'bg-accent-soft text-accent' : 'text-text-muted hover:bg-surface-2 hover:text-text',
                )}
              >
                <FileCode2 className="mt-0.5 size-3 shrink-0" aria-hidden />
                <span className="min-w-0">
                  <span className="block truncate text-[11px]">{name}</span>
                  {dir ? <span className="block truncate text-[10px] text-text-dim">{dir}</span> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="border-t border-border px-2 py-1 text-[10px] text-text-dim">
        {filtered.length} / {files.length} 个文件
      </p>
    </div>
  );
}

export function Breadcrumb({
  parts,
  onSelect,
}: {
  parts: string[];
  onSelect?: (index: number) => void;
}) {
  if (parts.length === 0) return null;
  return (
    <nav aria-label="代码位置" className="flex min-w-0 items-center gap-0.5 text-[11px] text-text-dim">
      {parts.map((part, index) => (
        <span key={`${part}-${index}`} className="flex min-w-0 items-center gap-0.5">
          {index > 0 ? <ChevronRight className="size-3 shrink-0 opacity-60" aria-hidden /> : null}
          {onSelect ? (
            <button
              type="button"
              onClick={() => onSelect(index)}
              className="max-w-[180px] truncate font-mono hover:text-accent"
            >
              {part}
            </button>
          ) : (
            <span className="max-w-[180px] truncate font-mono">{part}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

export function ReadOnlyBadge({ className }: { className?: string }) {
  return (
    <Badge tone="muted" className={className} title="这是只读的教学视图，不会执行仓库代码">
      <Lock className="size-2.5" aria-hidden />
      只读
    </Badge>
  );
}

export function FontSizeControls({
  value,
  onChange,
}: {
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <span className="flex items-center gap-1">
      <button
        type="button"
        aria-label="减小代码字号"
        onClick={() => onChange(Math.max(12, value - 1))}
        className="grid size-6 place-items-center rounded border border-border text-text-dim hover:text-text"
      >
        <Minus className="size-3" aria-hidden />
      </button>
      <span className="w-6 text-center font-mono text-[10px] text-text-dim">{value}</span>
      <button
        type="button"
        aria-label="增大代码字号"
        onClick={() => onChange(Math.min(16, value + 1))}
        className="grid size-6 place-items-center rounded border border-border text-text-dim hover:text-text"
      >
        <Plus className="size-3" aria-hidden />
      </button>
    </span>
  );
}
