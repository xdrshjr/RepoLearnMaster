'use client';

import Link from 'next/link';
import { Settings2 } from 'lucide-react';
import { useState } from 'react';

import { Badge, Card } from '@/components/ui/card';
import { Table } from '@/components/ui/table';
import { useToast } from '@/components/ui/toast';
import { SiteHeader } from '@/components/shell/site-header';
import { CostPanel } from '@/components/settings/cost-panel';
import { DoctorPanel } from '@/components/settings/doctor-panel';
import { ProfileList } from '@/components/settings/profile-list';
import { RevisionTimeline } from '@/components/settings/revision-timeline';
import { RoleMatrix } from '@/components/settings/role-matrix';
import { isApiError } from '@/lib/api/client';
import { readString } from '@/lib/api/types';
import {
  useActivateProfile,
  useDoctor,
  useHealthz,
  useMetrics,
  useProfiles,
  useRevisions,
  useRollbackRevision,
  useSetupState,
  useUpdateRoles,
} from '@/lib/api/hooks';

/**
 * Settings — spec §7.2 settings.
 *
 * Profile list + activate, role matrix, revision timeline with rollback, cost
 * panel and the doctor panel (gates G1/G2/G3 + DB + kernel + TTS + GitHub).
 */
export function SettingsView() {
  const toast = useToast();
  const profiles = useProfiles();
  const setupState = useSetupState();
  const revisions = useRevisions();
  const metrics = useMetrics();
  const doctor = useDoctor();
  const health = useHealthz();
  const activate = useActivateProfile();
  const updateRoles = useUpdateRoles();
  const rollback = useRollbackRevision();
  const [rollingBack, setRollingBack] = useState<number | null>(null);

  const notifyError = (error: unknown, fallback: string) => {
    const apiError = isApiError(error) ? error : null;
    toast.push({
      tone: 'error',
      title: apiError ? `${apiError.title} · ${apiError.code}` : fallback,
      description: apiError?.hint ?? (error instanceof Error ? error.message : undefined),
      action: apiError?.action,
    });
  };

  // 摘要只读已经拿到的数据，不额外发请求：设置页本身就够重了。
  const activeProfile = setupState.data?.active_profile ?? null;
  const kernels = (setupState.data?.kernel ?? {}) as unknown as Record<string, unknown>;
  const gates = (setupState.data?.gates ?? {}) as unknown as Record<string, unknown>;
  const roleCount = Object.values(setupState.data?.roles ?? {}).filter(
    (value) => typeof value === 'string' && value.length > 0,
  ).length;
  const configRows: Array<{ key: string; label: string; value: string }> = [
    {
      key: 'provider',
      label: '模型服务',
      value: activeProfile
        ? [activeProfile.provider, activeProfile.protocol].filter(Boolean).join(' · ')
        : '未配置',
    },
    {
      key: 'models',
      label: '模型',
      value: activeProfile?.models?.length ? activeProfile.models.join(', ') : '未记录',
    },
    { key: 'roles', label: '角色绑定', value: `${roleCount}/6` },
    {
      key: 'kernel',
      label: 'Agent 内核',
      value: kernels.ok === true ? readString(kernels, 'runtime', 'ok') : readString(kernels, 'mode', '未知'),
    },
    {
      key: 'gates',
      label: '门禁',
      value: `G1 ${String(gates.g1 ?? 'unknown')} · G2 ${String(gates.g2 ?? 'unknown')} · G3 ${String(gates.g3 ?? 'unknown')}`,
    },
  ];

  return (
    <>
      <SiteHeader context="设置 · AI 服务 / 角色 / 版本 / 诊断" />
      <main id="main" className="mx-auto w-full max-w-[1080px] space-y-3 px-4 py-6">
        <header className="flex flex-wrap items-center gap-2">
          <Settings2 className="size-4 text-accent" aria-hidden />
          <h1 className="text-base font-semibold text-text">设置</h1>
          {setupState.data?.active_profile ? (
            <Badge tone="accent">
              当前 profile：{setupState.data.active_profile.provider} ·{' '}
              {setupState.data.active_profile.models.slice(0, 2).join(', ') || '未记录模型'}
            </Badge>
          ) : (
            <Badge tone="warn">未配置</Badge>
          )}
          <Link href="/setup" className="ml-auto text-[11px] text-accent underline underline-offset-2">
            重新走一遍配置向导
          </Link>
        </header>

        <Card className="space-y-2">
          <h2 className="text-xs font-semibold text-text">当前配置</h2>
          {/*
            §3.3.2 D31：设置页原先是一堆会随内容变宽的 `<table>`/长字符串，窄屏上整页
            横向滚动。这里统一走 `ui/table.tsx`：`≥md` 是表格，`<md` 是 `<dl>` 卡片，
            每行都有 `<dt>` 标签，读屏可读，视觉上也不需要横向滑动。
          */}
          <Table
            responsive
            caption="当前配置摘要"
            columns={[
              { key: 'label', header: '项目', label: '项目', className: 'w-[7.5rem] whitespace-nowrap text-text-muted', cell: (row) => row.label },
              {
                key: 'value',
                header: '值',
                label: '值',
                cell: (row) => <span className="break-words font-mono text-[10px] text-text">{row.value}</span>,
              },
            ]}
            rows={configRows}
            rowKey={(row) => row.key}
          />
        </Card>

        <div className="grid gap-3 lg:grid-cols-2 [&>*]:min-w-0">
          <ProfileList
            profiles={profiles.data?.items ?? []}
            loading={profiles.isLoading}
            activatingId={activate.isPending ? (activate.variables ?? null) : null}
            refreshing={profiles.isFetching}
            onRefresh={() => {
              void profiles.refetch();
              void setupState.refetch();
            }}
            onActivate={(id) =>
              activate.mutate(id, {
                onSuccess: (data) => {
                  toast.push({
                    tone: 'success',
                    title: `已激活 · revision ${data.revision}`,
                    description: '角色分配同时生效；旧配置仍然可以回滚。',
                  });
                  void profiles.refetch();
                  void setupState.refetch();
                },
                onError: (error) => notifyError(error, '激活失败'),
              })
            }
          />

          <RoleMatrix
            roles={setupState.data?.roles ?? {}}
            saving={updateRoles.isPending}
            onSave={(roles) =>
              updateRoles.mutate(roles, {
                onSuccess: (data) => {
                  toast.push({ tone: 'success', title: `角色已保存 · revision ${data.revision}` });
                  void setupState.refetch();
                  void revisions.refetch();
                },
                onError: (error) => notifyError(error, '保存角色失败'),
              })
            }
          />

          <RevisionTimeline
            revisions={revisions.data?.items ?? []}
            loading={revisions.isLoading}
            rollingBack={rollingBack}
            onRollback={(rev) => {
              setRollingBack(rev);
              rollback.mutate(rev, {
                onSuccess: (data) => {
                  toast.push({ tone: 'success', title: `已回滚 · 新 revision ${data.revision}` });
                  void profiles.refetch();
                  void setupState.refetch();
                  void revisions.refetch();
                },
                onError: (error) => notifyError(error, '回滚失败'),
                onSettled: () => setRollingBack(null),
              });
            }}
          />

          <CostPanel metrics={metrics.data} loading={metrics.isLoading} />
        </div>

        <DoctorPanel
          checks={doctor.data?.checks ?? []}
          loading={doctor.isLoading}
          health={health.data}
          healthLoading={health.isLoading}
          refreshing={doctor.isFetching}
          onRefresh={() => {
            void doctor.refetch();
            void health.refetch();
          }}
        />

        <p className="pb-6 text-[10px] leading-[1.6] text-text-dim">
          密钥轮换通过 <code className="font-mono">POST /v1/settings/rotate-secret</code> 完成（同一事务重加密全部行）；
          日志对 <code className="font-mono">sk-</code> / <code className="font-mono">Bearer</code> 形状做全量脱敏。
        </p>
      </main>
    </>
  );
}
