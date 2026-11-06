'use client';

import { Check, TriangleAlert } from 'lucide-react';

import { Badge, Card } from '@/components/ui/card';
import type { RoleName } from '@/lib/api/types';
import { ROLE_LABELS, ROLE_ORDER } from '@/stores/setupWizard';

export function FinishStep({
  providerName,
  protocol,
  baseUrl,
  apiKey,
  modelCount,
  modelId,
  roles,
  ttsEnabled,
  ttsVoice,
  committed,
  warnings,
}: {
  providerName: string;
  protocol: string;
  baseUrl: string;
  apiKey: string;
  modelCount: number;
  modelId: string | null;
  roles: Record<RoleName, string>;
  ttsEnabled: boolean;
  ttsVoice: string;
  committed: { profile_id: string; revision: number } | null;
  warnings: string[];
}) {
  const maskedKey = apiKey ? `${apiKey.slice(0, 4)}···${apiKey.slice(-4)}` : '（使用服务端环境变量密钥）';

  return (
    <div className="space-y-4">
      {committed ? (
        <Card className="border-accent/40 bg-accent-soft">
          <p className="flex items-center gap-2 text-xs font-medium text-accent">
            <Check className="size-4" aria-hidden /> 配置已提交 · profile {committed.profile_id} · revision{' '}
            {committed.revision}
          </p>
          <p className="mt-1 text-[11px] text-text-muted">
            随时可以在设置里切换 profile 或回滚到上一个版本。
          </p>
        </Card>
      ) : null}

      <Card className="space-y-2">
        <h3 className="text-xs font-semibold text-text">模型服务</h3>
        <dl className="grid grid-cols-[92px_1fr] gap-x-3 gap-y-1.5 text-xs">
          <dt className="text-text-dim">服务商</dt>
          <dd className="text-text">{providerName}</dd>
          <dt className="text-text-dim">协议</dt>
          <dd className="font-mono text-[11px] text-text-muted">{protocol}</dd>
          {baseUrl ? (
            <>
              <dt className="text-text-dim">Base URL</dt>
              <dd className="break-all text-text-muted">{baseUrl}</dd>
            </>
          ) : null}
          <dt className="text-text-dim">密钥</dt>
          <dd className="text-text-muted">{maskedKey}（落库为密文，接口只回后 4 位）</dd>
          <dt className="text-text-dim">模型</dt>
          <dd className="text-text-muted">
            探测到 {modelCount} 个{modelId ? ` · 默认 ${modelId}` : ''}
          </dd>
          <dt className="text-text-dim">语音</dt>
          <dd className="text-text-muted">
            {ttsEnabled ? `豆包 TTS · ${ttsVoice}` : '未启用（字幕自动推进）'}
          </dd>
        </dl>
      </Card>

      <Card className="space-y-2">
        <h3 className="text-xs font-semibold text-text">角色分配</h3>
        <ul className="space-y-1 text-xs">
          {ROLE_ORDER.map((role) => (
            <li key={role} className="flex items-baseline justify-between gap-3">
              <span className="text-text-dim">{ROLE_LABELS[role].name}</span>
              <span className={roles[role] ? 'text-text' : 'text-warn'}>
                {roles[role] || (role === 'embed' ? '未分配（可选）' : '未分配')}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      {warnings.length > 0 ? (
        <Card className="border-warn/40 bg-warn/5">
          <p className="flex items-center gap-2 text-xs font-medium text-warn">
            <TriangleAlert className="size-4" aria-hidden /> 提交后有 {warnings.length} 条提醒
          </p>
          <ul className="mt-1 space-y-1">
            {warnings.map((warning) => (
              <li key={warning} className="text-[11px] text-text-muted">
                · {warning}
              </li>
            ))}
          </ul>
        </Card>
      ) : (
        <p className="text-[11px] text-text-dim">
          提交会写入 <span className="font-mono">settings_revisions</span>：切换服务商、改角色、回滚都会生成新 revision。
        </p>
      )}

      <div className="flex flex-wrap gap-2 text-[11px] text-text-dim">
        <Badge tone="muted">G1 依赖</Badge>
        <Badge tone="muted">G2 内核</Badge>
        <Badge tone="muted">G3 语音</Badge>
        <span>完成后可到设置 → 诊断面板查看三项 Gate 的实际状态。</span>
      </div>
    </div>
  );
}
