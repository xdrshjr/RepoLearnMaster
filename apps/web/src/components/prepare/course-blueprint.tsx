'use client';

import { AlertTriangle, Gauge, Layers, ShieldCheck } from 'lucide-react';

import { Badge, Card, CardHeader, ProgressBar } from '@/components/ui/card';
import { formatPercent } from '@/lib/format';
import { readArray, readNumber, readString } from '@/lib/api/types';

/**
 * Blueprint panel — the chapter skeletons the planner produced.
 *
 * `CourseDetail.blueprint` is `dict[str, Any]`, so rendering is defensive: we
 * look for a `chapters`/`outline` array of objects with a title, and otherwise
 * fall back to a key/value dump. A shape change on the backend degrades the
 * panel instead of crashing the preparation page.
 */
export function CourseBlueprint({
  blueprint,
  sections,
}: {
  blueprint: Record<string, unknown>;
  sections: Array<{ key: string; title: string; minutes: number; lessons: unknown[] }>;
}) {
  const chapters = readArray(blueprint, 'chapters');
  const outline = chapters.length > 0 ? chapters : readArray(blueprint, 'outline');

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <Layers className="size-3.5 text-accent" aria-hidden />
            课程蓝图
          </span>
        }
        subtitle={`${sections.length || outline.length || 4} 章 · ${
          sections.reduce((sum, section) => sum + section.lessons.length, 0) || '—'
        } 课时`}
      />
      {outline.length > 0 ? (
        <ol className="space-y-2">
          {outline.map((raw, index) => {
            const chapter = (raw ?? {}) as Record<string, unknown>;
            const title =
              readString(chapter, 'title') ||
              readString(chapter, 'name') ||
              readString(chapter, 'chapter') ||
              `第 ${index + 1} 章`;
            const lessons = readArray(chapter, 'lessons');
            const goal = readString(chapter, 'goal') || readString(chapter, 'summary');
            return (
              <li key={`${title}-${index}`} className="rounded-[var(--radius-sm)] border border-border px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="grid size-5 place-items-center rounded-full bg-surface-2 text-[10px] text-text-muted">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-text">{title}</span>
                  {lessons.length > 0 ? (
                    <span className="text-[10px] text-text-dim">{lessons.length} 课时</span>
                  ) : null}
                </div>
                {goal ? <p className="mt-1 pl-7 text-[11px] leading-[1.55] text-text-muted">{goal}</p> : null}
              </li>
            );
          })}
        </ol>
      ) : sections.length > 0 ? (
        <ol className="space-y-2">
          {sections.map((section, index) => (
            <li key={section.key} className="rounded-[var(--radius-sm)] border border-border px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="grid size-5 place-items-center rounded-full bg-surface-2 text-[10px] text-text-muted">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs font-medium text-text">{section.title}</span>
                <span className="text-[10px] text-text-dim">
                  {section.lessons.length} 课时 · {section.minutes} 分钟
                </span>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-[11px] text-text-dim">
          蓝图还没生成出来。它会随“规划章节”这一段一起点亮。
        </p>
      )}
    </Card>
  );
}

const CONFIDENCE_TONE: Record<string, 'accent' | 'warn' | 'danger' | 'muted'> = {
  high: 'accent',
  medium: 'warn',
  low: 'danger',
};

export function QualityPanel({ report }: { report: Record<string, unknown> }) {
  const anchorCoverage = readNumber(report, 'anchor_coverage', 0);
  const completeness = readNumber(report, 'lesson_completeness', 0);
  const degraded = report.degraded === true;
  const confidence = readString(report, 'anchor_confidence', 'unknown');
  const extra = Object.entries(report).filter(
    ([key]) => !['anchor_coverage', 'lesson_completeness', 'degraded', 'anchor_confidence'].includes(key),
  );

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <ShieldCheck className="size-3.5 text-accent" aria-hidden />
            质量面板
          </span>
        }
        subtitle="锚点覆盖率决定“能不能点着讲解跳回代码”，低于阈值会被标灰。"
        action={
          <Badge tone={CONFIDENCE_TONE[confidence] ?? 'muted'}>锚点置信度 {confidence}</Badge>
        }
      />
      <div className="space-y-3">
        <ProgressBar
          value={anchorCoverage <= 1 ? anchorCoverage * 100 : anchorCoverage}
          label="锚点覆盖率 anchor_coverage"
          tone={anchorCoverage >= 0.8 || anchorCoverage >= 80 ? 'accent' : 'warn'}
        />
        <ProgressBar
          value={completeness <= 1 ? completeness * 100 : completeness}
          label="课时完整度 lesson_completeness"
          tone={completeness >= 0.9 || completeness >= 90 ? 'accent' : 'warn'}
        />

        {degraded ? (
          <div className="flex items-start gap-2 rounded-[var(--radius-sm)] border border-warn/40 bg-warn/5 px-3 py-2">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
            <p className="text-[11px] leading-[1.6] text-text-muted">
              本次是降级生成：Kernel 不可用时按确定性骨架 + 模板话术产出，调用链只标为“静态推断”，
              不会伪造源码事实。
            </p>
          </div>
        ) : null}

        {report && Object.keys(report).length === 0 ? (
          <p className="text-[11px] text-text-dim">质量报告还没生成。</p>
        ) : null}

        {extra.length > 0 ? (
          <dl className="grid grid-cols-[130px_1fr] gap-x-2 gap-y-1 text-[11px]">
            {extra.slice(0, 8).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="truncate text-text-dim">{key}</dt>
                <dd className="truncate text-text-muted">
                  {typeof value === 'number'
                    ? key.includes('rate') || key.includes('coverage')
                      ? formatPercent(value)
                      : String(value)
                    : typeof value === 'string'
                      ? value
                      : JSON.stringify(value).slice(0, 80)}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}

        <div className="flex items-center gap-1.5 border-t border-border pt-2 text-[11px] text-text-dim">
          <Gauge className="size-3" aria-hidden />
          质量标准：锚点覆盖率 ≥ 80%、课时完整度 ≥ 90% 才算“可发布”。
        </div>
      </div>
    </Card>
  );
}
