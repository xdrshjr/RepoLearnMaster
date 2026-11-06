'use client';

import { Check } from 'lucide-react';

import { PROVIDERS, type ProviderKey } from '@/stores/setupWizard';
import { cn } from '@/lib/utils';

const VENDOR_MARK: Record<string, string> = {
  anthropic: 'A',
  openai: 'O',
  google: 'G',
  custom: '⚙',
};

export function ProviderSelect({
  value,
  onChange,
}: {
  value: ProviderKey | null;
  onChange: (key: ProviderKey) => void;
}) {
  return (
    <fieldset>
      <legend className="sr-only">选择模型服务</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {PROVIDERS.map((provider) => {
          const active = provider.key === value;
          return (
            <button
              key={provider.key}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(provider.key)}
              className={cn(
                'relative flex h-full flex-col gap-1.5 rounded-[var(--radius)] border p-3 text-left transition-colors',
                active
                  ? 'border-accent bg-accent-soft'
                  : 'border-border bg-surface hover:border-border-strong',
              )}
            >
              <div className="flex items-center gap-2">
                <span
                  aria-hidden
                  className={cn(
                    'grid size-7 place-items-center rounded-[var(--radius-sm)] text-xs font-semibold',
                    active ? 'bg-accent text-[#06110c]' : 'bg-surface-2 text-text-muted',
                  )}
                >
                  {VENDOR_MARK[provider.vendor] ?? provider.name.slice(0, 1)}
                </span>
                <span className="text-sm font-medium text-text">{provider.name}</span>
                {active ? <Check className="ml-auto size-4 text-accent" aria-hidden /> : null}
              </div>
              <p className="text-[11px] leading-[1.6] text-text-muted">{provider.blurb}</p>
              <p className="mt-auto text-[10px] text-text-dim">protocol: {provider.protocol}</p>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
