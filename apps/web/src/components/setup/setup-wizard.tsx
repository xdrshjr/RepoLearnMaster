'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Check, ChevronLeft, ChevronRight, CircleDot, PartyPopper } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { Badge, Card, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/toast';
import { CredentialsForm } from '@/components/setup/credentials-form';
import { FinishStep } from '@/components/setup/finish-step';
import { KernelNotReady } from '@/components/setup/kernel-not-ready';
import { ModelRoleMatrix } from '@/components/setup/model-role-matrix';
import { ProviderSelect } from '@/components/setup/provider-select';
import { TtsStep } from '@/components/setup/tts-step';
import { isApiError } from '@/lib/api/client';
import { useCommitSetup, useLlmProbe, useSetupState, useTtsProbe } from '@/lib/api/hooks';
import type { RoleName } from '@/lib/api/types';
import { providerOption, useSetupWizard } from '@/stores/setupWizard';
import { cn } from '@/lib/utils';

const STEP_TITLES = [
  '选择模型服务',
  '连通性与模型发现',
  '语音服务（可跳过）',
  '角色与默认模型',
  '完成',
];

export function SetupWizard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const toast = useToast();
  const store = useSetupWizard();
  const [mounted, setMounted] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);
  const [commitWarnings, setCommitWarnings] = useState<string[]>([]);

  const setupState = useSetupState();
  const llmProbe = useLlmProbe();
  const ttsProbe = useTtsProbe();
  const commit = useCommitSetup();

  const provider = providerOption(store.provider);
  const nextPath = searchParams.get('next');

  useEffect(() => setMounted(true), []);

  // `?step=` deep link (e.g. from an INVALID_KEY error) without losing input.
  useEffect(() => {
    if (!mounted) return;
    const raw = searchParams.get('step');
    if (!raw) return;
    const parsed = Number.parseInt(raw, 10);
    if (Number.isFinite(parsed) && parsed >= 1 && parsed <= 5) store.setStep(parsed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted, searchParams]);

  const probeTransportError = useMemo(() => {
    const error = llmProbe.data?.error;
    if (error) {
      return { code: error.code, message: error.message, hint: error.hint ?? '', retryable: error.retryable };
    }
    if (llmProbe.error) {
      const apiError = isApiError(llmProbe.error) ? llmProbe.error : null;
      return {
        code: apiError?.code ?? 'NETWORK',
        message: apiError?.message ?? llmProbe.error.message,
        hint: apiError?.hint ?? '',
        retryable: apiError?.retryable ?? true,
      };
    }
    return null;
  }, [llmProbe.data, llmProbe.error]);

  const ttsTransportError = useMemo(() => {
    const error = ttsProbe.data?.error;
    if (error) return { code: error.code, message: error.message, hint: error.hint ?? '' };
    if (ttsProbe.error) {
      const apiError = isApiError(ttsProbe.error) ? ttsProbe.error : null;
      return {
        code: apiError?.code ?? 'NETWORK',
        message: apiError?.message ?? ttsProbe.error.message,
        hint: apiError?.hint ?? '',
      };
    }
    return null;
  }, [ttsProbe.data, ttsProbe.error]);

  const runProbe = () => {
    if (!provider) return;
    llmProbe.mutate(
      {
        provider: provider.vendor,
        protocol: provider.protocol,
        api_key: store.apiKey,
        base_url: provider.needsBaseUrl ? store.baseUrl : undefined,
        org: store.org || undefined,
        model_id: store.modelId,
      },
      {
        onSuccess: (result) => {
          const data = result.data;
          if (data) {
            store.setProbe(data);
            if (!data.ok && data.error) {
              toast.push({
                tone: 'warn',
                title: `连通性未通过 · ${data.error.code}`,
                description: data.error.hint ?? data.error.message,
              });
            }
          } else {
            store.setProbe(null);
          }
        },
      },
    );
  };

  const submit = () => {
    if (!provider) return;
    const payload = {
      llm: {
        provider: provider.vendor,
        protocol: provider.protocol,
        api_key: store.apiKey,
        base_url: provider.needsBaseUrl ? store.baseUrl || null : null,
        org: store.org || null,
        label: store.label || `${provider.name} · ${new Date().toLocaleDateString('zh-CN')}`,
        model_id: store.modelId,
      },
      tts: store.ttsEnabled
        ? {
            provider: 'doubao' as const,
            app_id: store.tts.app_id,
            access_token: store.tts.access_token,
            cluster: store.tts.cluster,
            voice_type: store.tts.voice_type,
          }
        : null,
      roles: {
        planner: store.roles.planner,
        writer: store.roles.writer,
        critic: store.roles.critic,
        ...(store.roles.vision ? { vision: store.roles.vision } : {}),
        ...(store.roles.quiz ? { quiz: store.roles.quiz } : {}),
        ...(store.roles.embed ? { embed: store.roles.embed } : {}),
      },
    };

    commit.mutate(payload, {
      onSuccess: (data) => {
        store.setCommitted({ profile_id: data.profile_id, revision: data.revision });
        setCommitWarnings(data.warnings ?? []);
        toast.push({
          tone: 'success',
          title: '配置已完成',
          description: `已写入 revision ${data.revision}，正在前往首页…`,
        });
        const target = nextPath && nextPath.startsWith('/') ? nextPath : '/';
        window.setTimeout(() => {
          store.reset();
          router.push(target);
        }, 1600);
      },
      onError: (error) => {
        const apiError = isApiError(error) ? error : null;
        if (apiError?.code === 'INVALID_KEY') {
          store.setStep(2);
        }
        toast.push({
          tone: 'error',
          title: apiError ? `${apiError.title} · ${apiError.code}` : '提交失败',
          description: apiError?.hint ?? error.message,
        });
      },
    });
  };

  if (!mounted) {
    return (
      <div className="mx-auto w-full max-w-[860px] space-y-3 px-4 py-10">
        <Skeleton className="h-8 w-52" />
        <Skeleton className="h-56" />
      </div>
    );
  }

  // Rule 2 (§3.6.1): the wizard validates real state itself and shows a
  // "already configured" card instead of redirecting — no middleware ping-pong.
  if (setupState.isSuccess && !setupState.data.required) {
    return (
      <div className="mx-auto w-full max-w-[560px] px-4 py-14">
        <Card className="space-y-3 text-center">
          <PartyPopper className="mx-auto size-6 text-accent" aria-hidden />
          <h1 className="text-base font-semibold text-text">已配置完成</h1>
          <p className="text-xs text-text-muted">
            当前激活的 profile 是{' '}
            <span className="font-mono text-text">{setupState.data.active_profile?.provider ?? 'unknown'}</span>
            （{setupState.data.active_profile?.models?.join(', ') || '未记录模型'}）。
          </p>
          <div className="flex justify-center gap-2">
            <Button variant="primary" onClick={() => router.push('/')}>
              回首页
            </Button>
            <Button variant="outline" onClick={() => router.push('/settings')}>
              查看 / 修改配置
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  const step = store.step;

  return (
    <div className="mx-auto grid w-full max-w-[1000px] gap-6 px-4 py-8 lg:grid-cols-[210px_1fr]">
      <aside className="space-y-3">
        <div>
          <h1 className="text-lg font-semibold text-text">配置 AI 服务</h1>
          <p className="mt-1 text-[11px] leading-[1.6] text-text-muted">
            五步完成后即可生成课程。中途退出不会丢输入（草稿存在 sessionStorage）。
          </p>
        </div>
        <ol className="space-y-1">
          {STEP_TITLES.map((title, index) => {
            const value = index + 1;
            const active = value === step;
            const done = value < step || store.maxStepReached > value;
            return (
              <li key={title}>
                <button
                  type="button"
                  onClick={() => store.setStep(value)}
                  aria-current={active ? 'step' : undefined}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-xs transition-colors',
                    active ? 'bg-accent-soft text-accent' : 'text-text-muted hover:bg-surface-2 hover:text-text',
                  )}
                >
                  <span
                    aria-hidden
                    className={cn(
                      'grid size-5 shrink-0 place-items-center rounded-full border text-[10px]',
                      active
                        ? 'border-accent bg-accent text-[#06110c]'
                        : done
                          ? 'border-accent/50 text-accent'
                          : 'border-border text-text-dim',
                    )}
                  >
                    {done && !active ? <Check className="size-3" aria-hidden /> : value}
                  </span>
                  <span className="truncate">{title}</span>
                </button>
              </li>
            );
          })}
        </ol>

        {setupState.data ? (
          <Card className="space-y-1 text-[11px]">
            <p className="text-text-dim">内核</p>
            <p className="text-text-muted">
              {setupState.data.kernel.ok ? '在线' : '离线'} · runtime {setupState.data.kernel.runtime}
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              <Badge tone={setupState.data.gates.g1 === 'ok' ? 'accent' : 'muted'}>G1 {setupState.data.gates.g1}</Badge>
              <Badge tone={setupState.data.gates.g2 === 'ok' ? 'accent' : 'muted'}>G2 {setupState.data.gates.g2}</Badge>
              <Badge tone={setupState.data.gates.g3 === 'ok' ? 'accent' : 'muted'}>G3 {setupState.data.gates.g3}</Badge>
            </div>
          </Card>
        ) : null}
      </aside>

      <section className="space-y-4">
        {setupState.isError ? (
          <KernelNotReady
            message={
              isApiError(setupState.error)
                ? setupState.error.message
                : '无法读取 /api/setup/state，可能是后端进程没有启动。'
            }
            hint={isApiError(setupState.error) ? setupState.error.hint : undefined}
            onRetry={() => void setupState.refetch()}
            retrying={setupState.isFetching}
          />
        ) : null}

        <Card className="space-y-4">
          <header className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-text-dim">第 {step} / 5 步</p>
              <h2 className="mt-0.5 text-sm font-semibold text-text">{STEP_TITLES[step - 1]}</h2>
            </div>
            <CircleDot className="size-4 text-text-dim" aria-hidden />
          </header>

          {step === 1 ? (
            <ProviderSelect value={store.provider} onChange={store.selectProvider} />
          ) : null}

          {step === 2 ? (
            provider ? (
              <CredentialsForm
                provider={provider}
                apiKey={store.apiKey}
                baseUrl={store.baseUrl}
                org={store.org}
                modelId={store.modelId}
                probe={store.probe}
                probing={llmProbe.isPending}
                transportError={probeTransportError}
                onChange={store.patch}
                onTest={runProbe}
                onSelectModel={(id) => store.patch({ modelId: id })}
              />
            ) : (
              <p className="text-xs text-warn">先回到第 1 步选择一个模型服务。</p>
            )
          ) : null}

          {step === 3 ? (
            <TtsStep
              enabled={store.ttsEnabled}
              tts={store.tts}
              probe={store.ttsProbe}
              probing={ttsProbe.isPending}
              transportError={ttsTransportError}
              onToggle={store.setTtsEnabled}
              onChange={store.patchTts}
              onSkipAll={() => {
                store.setTtsEnabled(false);
                store.next();
              }}
              onProbe={() =>
                ttsProbe.mutate(
                  {
                    app_id: store.tts.app_id,
                    access_token: store.tts.access_token,
                    cluster: store.tts.cluster,
                    voice_type: store.tts.voice_type,
                    text: '你好，这里是 RepoLearn',
                  },
                  {
                    onSuccess: (result) => {
                      if (result.data) store.setTtsProbe(result.data);
                      else store.setTtsProbe(null);
                    },
                  },
                )
              }
            />
          ) : null}

          {step === 4 ? (
            <ModelRoleMatrix
              roles={store.roles}
              models={store.probe?.models ?? []}
              notes={notes}
              onChange={(role: RoleName, modelId: string) => store.setRole(role, modelId)}
              onAutoAssign={() => setNotes(store.applyAutoAssign())}
              onReset={() => {
                for (const role of ['planner', 'writer', 'critic', 'vision', 'quiz', 'embed'] as RoleName[]) {
                  store.setRole(role, '');
                }
                setNotes([]);
              }}
            />
          ) : null}

          {step === 5 ? (
            provider ? (
              <FinishStep
                providerName={provider.name}
                protocol={provider.protocol}
                baseUrl={provider.needsBaseUrl ? store.baseUrl : ''}
                apiKey={store.apiKey}
                modelCount={store.probe?.models.length ?? 0}
                modelId={store.modelId}
                roles={store.roles}
                ttsEnabled={store.ttsEnabled}
                ttsVoice={store.tts.voice_type}
                committed={store.committed}
                warnings={commitWarnings}
              />
            ) : (
              <p className="text-xs text-warn">先回到第 1 步选择一个模型服务。</p>
            )
          ) : null}

          <footer className="flex items-center justify-between gap-2 border-t border-border pt-3">
            <Button
              variant="ghost"
              onClick={store.back}
              disabled={step === 1}
              icon={<ChevronLeft className="size-4" aria-hidden />}
            >
              上一步
            </Button>
            <div className="flex items-center gap-2">
              {step === 2 && !store.probe?.ok ? (
                <Button variant="ghost" size="sm" onClick={store.next}>
                  先跳过测试
                </Button>
              ) : null}
              {step < 5 ? (
                <Button
                  variant="primary"
                  onClick={store.next}
                  disabled={step === 1 && !store.provider}
                  icon={<ChevronRight className="size-4" aria-hidden />}
                >
                  下一步
                </Button>
              ) : (
                <Button
                  variant="primary"
                  onClick={submit}
                  loading={commit.isPending}
                  disabled={!store.roles.planner || !store.roles.writer || !store.roles.critic}
                  icon={<Check className="size-4" aria-hidden />}
                >
                  完成配置
                </Button>
              )}
            </div>
          </footer>
        </Card>

        <p className="text-[11px] leading-[1.6] text-text-dim">
          密钥经 Fernet 加密后落库，出站接口只回传后 4 位；日志对 <code className="font-mono">sk-</code> /{' '}
          <code className="font-mono">Bearer</code> 形状做全量脱敏。
        </p>
      </section>
    </div>
  );
}
