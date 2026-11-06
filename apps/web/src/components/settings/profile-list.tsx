'use client';

import { CheckCircle2, KeyRound, RefreshCw } from 'lucide-react';

import { Badge, Card, CardHeader, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { ProfileItem } from '@/lib/api/types';
import { formatDateTime, formatRelativeTime } from '@/lib/format';

export function ProfileList({
  profiles,
  loading,
  activatingId,
  onActivate,
  onRefresh,
  refreshing,
}: {
  profiles: ProfileItem[];
  loading: boolean;
  activatingId: string | null;
  onActivate: (id: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  return (
    <Card id="profiles">
      <CardHeader
        title="模型服务 Profile"
        subtitle="激活即生成新的 revision；密钥只显示后 4 位。"
        action={
          <Button variant="ghost" size="sm" onClick={onRefresh} loading={refreshing} icon={<RefreshCw className="size-3" aria-hidden />}>
            刷新
          </Button>
        }
      />
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : profiles.length === 0 ? (
        <p className="text-[11px] text-text-dim">
          还没有配置任何 profile。打开 <a className="text-accent underline" href="/setup">配置向导</a> 添加第一个。
        </p>
      ) : (
        <ul className="space-y-2">
          {profiles.map((profile) => {
            const probeOk = profile.last_probe?.ok !== false;
            return (
              <li
                key={profile.id}
                className="flex flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-border px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5 text-xs text-text">
                    <span className="truncate">{profile.label || profile.provider}</span>
                    {profile.active ? <Badge tone="accent">使用中</Badge> : null}
                    {!probeOk ? <Badge tone="warn">上次探测失败</Badge> : null}
                  </p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-2 text-[10px] text-text-dim">
                    <span className="font-mono">{profile.protocol}</span>
                    <span>{profile.model_count} 个模型</span>
                    <span className="inline-flex items-center gap-0.5">
                      <KeyRound className="size-2.5" aria-hidden />···{profile.api_key_last4 || '----'}
                    </span>
                    {profile.base_url ? <span className="truncate">{profile.base_url}</span> : null}
                    <span>{profile.created_at ? `${formatRelativeTime(profile.created_at)}创建` : ''}</span>
                  </p>
                </div>
                {profile.active ? (
                  <span className="inline-flex items-center gap-1 text-[11px] text-accent">
                    <CheckCircle2 className="size-3.5" aria-hidden />
                    已激活
                  </span>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onActivate(profile.id)}
                    loading={activatingId === profile.id}
                  >
                    激活
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {profiles.length > 0 ? (
        <p className="mt-2 text-[10px] text-text-dim">
          最后更新时间：{formatDateTime(profiles[0]?.created_at ?? null)}
        </p>
      ) : null}
    </Card>
  );
}
