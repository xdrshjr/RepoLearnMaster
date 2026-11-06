'use client';

import { Save } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Card, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import type { RoleName } from '@/lib/api/types';
import { ROLE_NAMES } from '@/lib/api/types';
import { ROLE_LABELS } from '@/stores/setupWizard';

export function RoleMatrix({
  roles,
  saving,
  onSave,
}: {
  roles: Record<string, string>;
  saving: boolean;
  onSave: (roles: Record<string, string>) => void;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({ ...roles });

  useEffect(() => {
    setDraft({ ...roles });
  }, [roles]);

  const dirty = ROLE_NAMES.some((role) => (draft[role] ?? '') !== (roles[role] ?? ''));

  return (
    <Card id="roles">
      <CardHeader
        title="角色与默认模型"
        subtitle="六个角色各自绑定模型；缺少 planner/writer/critic 会返回 NO_MODEL_FOR_ROLE。"
        action={
          <Button
            variant="primary"
            size="sm"
            onClick={() => onSave(draft)}
            loading={saving}
            disabled={!dirty}
            icon={<Save className="size-3" aria-hidden />}
          >
            保存
          </Button>
        }
      />
      <div className="overflow-hidden rounded-[var(--radius-sm)] border border-border">
        <table className="w-full border-collapse text-[11px]">
          <thead>
            <tr className="bg-surface-2 text-left text-[10px] text-text-dim">
              <th className="px-2 py-1.5 font-medium">角色</th>
              <th className="px-2 py-1.5 font-medium">模型 ID</th>
            </tr>
          </thead>
          <tbody>
            {ROLE_NAMES.map((role) => (
              <tr key={role} className="border-t border-border">
                <td className="px-2 py-1.5 align-top">
                  <p className="text-text">{ROLE_LABELS[role as RoleName].name}</p>
                  <p className="mt-0.5 text-[10px] leading-[1.5] text-text-dim">
                    {ROLE_LABELS[role as RoleName].description}
                  </p>
                </td>
                <td className="px-2 py-1.5">
                  <TextInput
                    value={draft[role] ?? ''}
                    placeholder={role === 'embed' ? '（可选）留空则不启用向量检索' : '例如 claude-sonnet-4-5'}
                    spellCheck={false}
                    aria-label={`${role} 的模型`}
                    className="h-8 font-mono text-[11px]"
                    onChange={(event) => setDraft((current) => ({ ...current, [role]: event.target.value }))}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {dirty ? <p className="mt-2 text-[10px] text-warn">有未保存的修改。</p> : null}
    </Card>
  );
}
