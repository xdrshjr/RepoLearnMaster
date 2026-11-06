'use client';

import { Wand2 } from 'lucide-react';

import { Badge } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { InlineNote, Select, TextInput } from '@/components/ui/field';
import type { ModelItem, RoleName } from '@/lib/api/types';
import { ROLE_LABELS, ROLE_ORDER } from '@/stores/setupWizard';

function issuesFor(roles: Record<RoleName, string>, models: ModelItem[]): string[] {
  const issues: string[] = [];
  for (const role of ['planner', 'writer', 'critic'] as RoleName[]) {
    if (!roles[role]) issues.push(`${role} 必须先选一个模型（生成会返回 NO_MODEL_FOR_ROLE）。`);
  }
  const allRoles = new Set(models.map((model) => model.id));
  for (const role of ROLE_ORDER) {
    const value = roles[role];
    if (value && models.length > 0 && !allRoles.has(value)) {
      issues.push(`${role} 的模型 ${value} 不在探测结果里，保存前请确认模型 ID。`);
    }
  }
  return issues;
}

export function ModelRoleMatrix({
  roles,
  models,
  onChange,
  onAutoAssign,
  onReset,
  notes,
}: {
  roles: Record<RoleName, string>;
  models: ModelItem[];
  onChange: (role: RoleName, modelId: string) => void;
  onAutoAssign: () => void;
  onReset: () => void;
  notes: string[];
}) {
  const visionModels = models.filter((model) => model.capabilities.vision);
  const issues = issuesFor(roles, models);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" onClick={onAutoAssign} icon={<Wand2 className="size-3.5" aria-hidden />}>
          按能力自动分配
        </Button>
        <Button variant="ghost" size="sm" onClick={onReset}>
          清空
        </Button>
        <span className="text-[11px] text-text-dim">
          按上下文窗口 / JSON 能力 / 单价自动挑，之后仍可逐个改。
        </span>
      </div>

      <div className="overflow-hidden rounded-[var(--radius)] border border-border">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="bg-surface-2 text-left text-[11px] text-text-muted">
              <th className="px-3 py-2 font-medium">角色</th>
              <th className="px-3 py-2 font-medium">模型</th>
            </tr>
          </thead>
          <tbody>
            {ROLE_ORDER.map((role) => {
              const meta = ROLE_LABELS[role];
              const value = roles[role];
              const isVision = role === 'vision';
              return (
                <tr key={role} className="border-t border-border align-top">
                  <td className="w-[45%] px-3 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className="text-text">{meta.name}</span>
                      {role === 'embed' ? <Badge tone="muted">可选</Badge> : null}
                      {isVision && visionModels.length === 0 ? <Badge tone="warn">退化</Badge> : null}
                    </div>
                    <p className="mt-1 text-[11px] leading-[1.55] text-text-dim">{meta.description}</p>
                    {isVision && visionModels.length === 0 ? (
                      <p className="mt-1 text-[11px] text-warn">
                        没有多模态模型：README 图表理解会被跳过（记 VISION_SKIPPED）。
                      </p>
                    ) : null}
                  </td>
                  <td className="px-3 py-2.5">
                    {models.length > 0 ? (
                      <Select
                        aria-label={`${role} 的模型`}
                        value={value}
                        onChange={(event) => onChange(role, event.target.value)}
                      >
                        <option value="">未分配</option>
                        {models.map((model) => (
                          <option key={model.id} value={model.id}>
                            {model.display_name || model.id}
                            {model.capabilities.vision ? ' · vision' : ''}
                            {model.capabilities.json_mode ? ' · json' : ''}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <TextInput
                        aria-label={`${role} 的模型 ID`}
                        value={value}
                        placeholder="手动输入模型 ID，例如 claude-sonnet-4-5"
                        spellCheck={false}
                        onChange={(event) => onChange(role, event.target.value)}
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {notes.length > 0 ? (
        <ul className="space-y-1">
          {notes.map((note) => (
            <li key={note} className="text-[11px] text-text-dim">
              · {note}
            </li>
          ))}
        </ul>
      ) : null}

      {issues.length > 0 ? (
        <div className="rounded-[var(--radius-sm)] border border-warn/40 bg-warn/5 px-3 py-2">
          {issues.map((issue) => (
            <p key={issue} className="text-[11px] text-warn">
              {issue}
            </p>
          ))}
        </div>
      ) : (
        <InlineNote>六个角色都检查通过，可以提交配置。</InlineNote>
      )}
    </div>
  );
}
