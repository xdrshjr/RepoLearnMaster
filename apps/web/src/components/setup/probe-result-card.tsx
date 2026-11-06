'use client';

import { Check, Eye, FileJson, Timer, Wrench, X } from 'lucide-react';

import { Badge, Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/field';
import type { LlmProbeResponse, ModelItem } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import { cn } from '@/lib/utils';

export function CapabilityBadges({ model }: { model: ModelItem }) {
  const caps = model.capabilities;
  const items: Array<{ key: string; label: string; on: boolean; icon: typeof Eye }> = [
    { key: 'text', label: 'text', on: caps.text, icon: Check },
    { key: 'vision', label: 'vision', on: caps.vision, icon: Eye },
    { key: 'tools', label: 'tools', on: caps.tools, icon: Wrench },
    { key: 'json', label: 'json', on: caps.json_mode, icon: FileJson },
  ];
  return (
    <span className="flex flex-wrap items-center gap-1">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <span
            key={item.key}
            title={`${item.label}: ${item.on ? '支持' : '不支持'}`}
            className={cn(
              'inline-flex items-center gap-0.5 rounded border px-1.5 py-0.5 text-[10px]',
              item.on
                ? 'border-accent/30 bg-accent-soft text-accent'
                : 'border-border bg-transparent text-text-dim line-through',
            )}
          >
            <Icon className="size-2.5" aria-hidden />
            {item.label}
          </span>
        );
      })}
    </span>
  );
}

export function ProbeResultCard({
  probe,
  transportError,
  selectedModel,
  onSelectModel,
  onRetry,
  retrying,
}: {
  probe: LlmProbeResponse | null;
  transportError?: { code: string; message: string; hint: string; retryable: boolean } | null;
  selectedModel: string | null;
  onSelectModel: (id: string) => void;
  onRetry: () => void;
  retrying: boolean;
}) {
  if (!probe && !transportError) return null;

  if (transportError) {
    return (
      <Card className="border-danger/40 bg-danger/5">
        <div className="flex items-start gap-2">
          <X className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-danger">
              测试请求失败 · {transportError.code}
            </p>
            <p className="mt-1 text-xs text-text-muted">{transportError.message}</p>
            <p className="mt-1 text-[11px] text-text-dim">{transportError.hint}</p>
          </div>
          <Button variant="outline" size="sm" onClick={onRetry} loading={retrying}>
            重试
          </Button>
        </div>
      </Card>
    );
  }

  if (probe && !probe.ok) {
    const error = probe.error;
    return (
      <Card className="border-warn/40 bg-warn/5">
        <div className="flex items-start gap-2">
          <X className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-warn">
              连通性测试未通过{error ? ` · ${error.code}` : ''}
            </p>
            {error ? <p className="mt-1 text-xs text-text-muted">{error.message}</p> : null}
            {error?.hint ? <p className="mt-1 text-[11px] text-text-dim">{error.hint}</p> : null}
            <p className="mt-2 text-[11px] text-text-dim">
              这一步失败不影响向导继续：可以改 Key 重试，也可以先去第 4 步手动填模型名。
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={onRetry} loading={retrying}>
            重试
          </Button>
        </div>
      </Card>
    );
  }

  if (!probe) return null;

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent">
          <Check className="size-3" aria-hidden /> 连接成功
        </Badge>
        <span className="inline-flex items-center gap-1 text-[11px] text-text-muted">
          <Timer className="size-3" aria-hidden />
          延迟 {probe.latency_ms} ms
        </span>
        <span className="text-[11px] text-text-dim">发现 {probe.models.length} 个模型</span>
      </div>

      {probe.models.length > 0 ? (
        <>
          <div className="max-h-64 space-y-1 overflow-y-auto pr-1">
            {probe.models.map((model) => {
              const active = model.id === selectedModel;
              return (
                <button
                  key={model.id}
                  type="button"
                  onClick={() => onSelectModel(model.id)}
                  aria-pressed={active}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-[var(--radius-sm)] border px-2.5 py-2 text-left transition-colors',
                    active
                      ? 'border-accent bg-accent-soft'
                      : 'border-border bg-surface-2/40 hover:border-border-strong',
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs text-text">
                      {model.display_name || model.id}
                    </span>
                    <span className="block truncate text-[10px] text-text-dim">
                      {model.id}
                      {model.context_window || model.capabilities.context_window
                        ? ` · ${formatCount(model.context_window || model.capabilities.context_window)} ctx`
                        : ''}
                    </span>
                  </span>
                  <CapabilityBadges model={model} />
                </button>
              );
            })}
          </div>
          <Select
            aria-label="选择默认模型"
            value={selectedModel ?? ''}
            onChange={(event) => onSelectModel(event.target.value)}
          >
            <option value="">选择默认模型…</option>
            {probe.models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.display_name || model.id}
                {model.capabilities.vision ? ' · 支持图片' : ''}
                {model.capabilities.json_mode ? ' · JSON' : ''}
              </option>
            ))}
          </Select>
        </>
      ) : (
        <p className="text-[11px] text-warn">
          连接成功但没有返回模型列表：可直接在第 4 步手填模型 ID（网关常常不实现 /models）。
        </p>
      )}
    </Card>
  );
}
