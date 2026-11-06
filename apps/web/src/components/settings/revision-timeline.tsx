'use client';

import { History, RotateCcw } from 'lucide-react';

import { Badge, Card, CardHeader, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { RevisionItem } from '@/lib/api/types';
import { formatDateTime } from '@/lib/format';

export function RevisionTimeline({
  revisions,
  loading,
  rollingBack,
  onRollback,
}: {
  revisions: RevisionItem[];
  loading: boolean;
  rollingBack: number | null;
  onRollback: (rev: number) => void;
}) {
  return (
    <Card id="revisions">
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <History className="size-3.5 text-accent" aria-hidden />
            版本时间线
          </span>
        }
        subtitle="回滚会生成一个新 revision 指向旧内容（历史不可变）。"
      />
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : revisions.length === 0 ? (
        <p className="text-[11px] text-text-dim">还没有 revision 记录。</p>
      ) : (
        <ol className="relative space-y-3 border-l border-border pl-3">
          {revisions.map((revision, index) => (
            <li key={revision.id} className="relative">
              <span
                aria-hidden
                className={`absolute -left-[17px] top-1.5 size-2.5 rounded-full border ${
                  index === 0 ? 'border-accent bg-accent' : 'border-border bg-bg'
                }`}
              />
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-[11px] text-accent">rev {revision.rev}</span>
                {index === 0 ? <Badge tone="accent">当前</Badge> : null}
                <span className="text-[10px] text-text-dim">{formatDateTime(revision.created_at)}</span>
                <span className="text-[10px] text-text-dim">· {revision.author}</span>
                <span className="ml-auto">
                  {index === 0 ? null : (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onRollback(revision.rev)}
                      loading={rollingBack === revision.rev}
                      icon={<RotateCcw className="size-3" aria-hidden />}
                    >
                      回滚到此版
                    </Button>
                  )}
                </span>
              </div>
              <p className="mt-0.5 text-[11px] text-text-muted">{revision.summary || '（无摘要）'}</p>
              {revision.changes.length > 0 ? (
                <ul className="mt-1 space-y-0.5">
                  {revision.changes.slice(0, 5).map((change) => (
                    <li key={change} className="font-mono text-[10px] text-text-dim">
                      · {change}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
