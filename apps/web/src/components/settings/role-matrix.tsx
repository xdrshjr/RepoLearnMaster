'use client';

import { Save } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Card, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { Table, type TableColumn } from '@/components/ui/table';
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

  // §3.3.2 D31：宽表在 `<md` 下改成 `<dl>` 卡片（`ui/table.tsx`），不再横向溢出。
  // 每一行的输入框都有**显式、唯一**的 aria-label：读屏时"六个同名输入框"与
  // "没有名字的输入框"是同一类缺陷——用户分不出自己在改哪个角色。
  const columns: Array<TableColumn<RoleName>> = [
    {
      key: 'role',
      header: '角色',
      label: '角色',
      className: 'min-w-[9rem]',
      cell: (role) => (
        <div>
          <p className="text-text">{ROLE_LABELS[role].name}</p>
          <p className="mt-0.5 text-[10px] leading-[1.5] text-text-dim">
            {ROLE_LABELS[role].description}
          </p>
        </div>
      ),
    },
    {
      key: 'model',
      header: '模型 ID',
      label: '模型 ID',
      cell: (role) => (
        <TextInput
          value={draft[role] ?? ''}
          placeholder={role === 'embed' ? '（可选）留空则不启用向量检索' : '例如 claude-sonnet-4-5'}
          spellCheck={false}
          aria-label={`${ROLE_LABELS[role].name}（${role}）使用的模型 ID`}
          className="h-9 w-full font-mono text-[11px] md:h-8"
          onChange={(event) => setDraft((current) => ({ ...current, [role]: event.target.value }))}
        />
      ),
    },
  ];

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
            data-rl-tap=""
            className="max-lg:min-h-[var(--tap-target)] max-lg:min-w-[var(--tap-target)]"
            icon={<Save className="size-3" aria-hidden />}
          >
            保存
          </Button>
        }
      />
      <Table
        responsive
        caption="角色与默认模型"
        columns={columns}
        rows={ROLE_NAMES}
        rowKey={(role) => role}
      />
      {dirty ? <p className="mt-2 text-[10px] text-warn">有未保存的修改。</p> : null}
    </Card>
  );
}
