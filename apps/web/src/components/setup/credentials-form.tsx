'use client';

import { KeyRound, Link2, PlugZap } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Field, InlineNote, TextInput } from '@/components/ui/field';
import { ProbeResultCard } from '@/components/setup/probe-result-card';
import type { LlmProbeResponse } from '@/lib/api/types';
import type { ProviderOption } from '@/stores/setupWizard';

export function CredentialsForm({
  provider,
  apiKey,
  baseUrl,
  org,
  modelId,
  probe,
  probing,
  transportError,
  onChange,
  onTest,
  onSelectModel,
}: {
  provider: ProviderOption;
  apiKey: string;
  baseUrl: string;
  org: string;
  modelId: string | null;
  probe: LlmProbeResponse | null;
  probing: boolean;
  transportError: { code: string; message: string; hint: string; retryable: boolean } | null;
  onChange: (patch: { apiKey?: string; baseUrl?: string; org?: string }) => void;
  onTest: () => void;
  onSelectModel: (id: string) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-3">
        <Field
          label={provider.needsBaseUrl ? 'Base URL' : 'API Key'}
          htmlFor="setup-api-key"
          required={!provider.needsBaseUrl}
          hint={`密钥只会以密文落库，接口只回传后 4 位。形如 ${provider.keyHint}`}
        >
          <div className="relative">
            <KeyRound className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-text-dim" aria-hidden />
            <TextInput
              id="setup-api-key"
              type="password"
              value={apiKey}
              autoComplete="off"
              spellCheck={false}
              placeholder={provider.keyHint}
              onChange={(event) => onChange({ apiKey: event.target.value })}
              className="pl-8"
            />
          </div>
        </Field>

        {provider.needsBaseUrl ? (
          <Field
            label="Base URL"
            htmlFor="setup-base-url"
            required
            hint={provider.baseUrlPlaceholder}
          >
            <div className="relative">
              <Link2 className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-text-dim" aria-hidden />
              <TextInput
                id="setup-base-url"
                type="url"
                value={baseUrl}
                placeholder={provider.baseUrlPlaceholder}
                spellCheck={false}
                onChange={(event) => onChange({ baseUrl: event.target.value })}
                className="pl-8"
              />
            </div>
          </Field>
        ) : null}

        <Field label="组织 ID（可选）" htmlFor="setup-org" hint="OpenAI 的 org、Azure 的 deployment 之类，留空即可">
          <TextInput
            id="setup-org"
            value={org}
            placeholder="org_..."
            spellCheck={false}
            onChange={(event) => onChange({ org: event.target.value })}
          />
        </Field>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          size="md"
          onClick={onTest}
          loading={probing}
          icon={<PlugZap className="size-4" aria-hidden />}
        >
          {probing ? '正在测试…' : '测试连接'}
        </Button>
        <span className="text-[11px] text-text-dim">
          会请求一次模型列表并测量延迟；失败会给出可执行的建议，不会锁住向导。
        </span>
      </div>

      {!provider.needsBaseUrl && !apiKey ? (
        <InlineNote>
          服务端环境变量里若已配置密钥，后端会优先使用它；但 <code className="font-mono">probe</code> 请求本身要求
          <code className="mx-1 font-mono">api_key</code> 非空，所以这里仍需填一个值才能通过校验。
        </InlineNote>
      ) : null}

      <ProbeResultCard
        probe={probe}
        transportError={transportError}
        selectedModel={modelId}
        onSelectModel={onSelectModel}
        onRetry={onTest}
        retrying={probing}
      />
    </div>
  );
}
