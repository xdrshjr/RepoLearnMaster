'use client';

import { useMemo } from 'react';

import { Card } from '@/components/ui/card';

const DEFAULT_DIMENSIONS: Array<{ key: string; label: string }> = [
  { key: 'architecture', label: '架构理解' },
  { key: 'call_chain', label: '调用链' },
  { key: 'source_reading', label: '源码细节' },
  { key: 'debugging', label: '调试推演' },
  { key: 'engineering', label: '工程权衡' },
];

const LABEL_HINTS: Record<string, string> = {
  architecture: '架构理解',
  call_chain: '调用链',
  source_reading: '源码细节',
  debugging: '调试推演',
  engineering: '工程权衡',
  overview: '架构理解',
  walkthrough: '调用链',
  deep_dive: '源码细节',
  quiz: '细节记忆',
  speed: '学习效率',
};

function normalize(scores: Record<string, number>): Array<{ label: string; value: number }> {
  const entries = Object.entries(scores ?? {});
  const points =
    entries.length >= 5
      ? entries
          .sort((a, b) => b[1] - a[1])
          .slice(0, 5)
          .map(([key, value]) => ({ label: LABEL_HINTS[key] ?? key, value }))
      : [
          ...entries.map(([key, value]) => ({ label: LABEL_HINTS[key] ?? key, value })),
          ...DEFAULT_DIMENSIONS.filter((dimension) => !(dimension.key in scores)).map((dimension) => ({
            label: dimension.label,
            value: 0,
          })),
        ].slice(0, 5);

  while (points.length < 5) points.push({ label: '待评估', value: 0 });
  return points.map((point) => ({
    label: point.label,
    // Accept 0–1 ratios or 0–100 scores.
    value: Math.max(0, Math.min(100, point.value <= 1 ? point.value * 100 : point.value)),
  }));
}

/**
 * Five-dimension ability radar — hand-rolled inline SVG.
 *
 * The spec explicitly forbids adding a charting dependency for this (§7.2
 * 课程总结), so the polygon, grid and labels are computed here.
 */
export function AbilityRadar({
  scores,
  size = 220,
}: {
  scores: Record<string, number>;
  size?: number;
}) {
  const points = useMemo(() => normalize(scores ?? {}), [scores]);
  const center = size / 2;
  const radius = center - 34;

  const toPoint = (index: number, ratio: number) => {
    const angle = (Math.PI * 2 * index) / points.length - Math.PI / 2;
    return {
      x: center + Math.cos(angle) * radius * ratio,
      y: center + Math.sin(angle) * radius * ratio,
    };
  };

  const polygon = points
    .map((point, index) => {
      const { x, y } = toPoint(index, point.value / 100);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <Card className="space-y-1">
      <h3 className="text-xs font-semibold text-text">五维能力</h3>
      <p className="text-[10px] text-text-dim">基于本次答题与走读完成度估算，不是考试分数。</p>
      <div className="flex justify-center">
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          role="img"
          aria-label={`五维能力雷达图：${points.map((point) => `${point.label} ${Math.round(point.value)}分`).join('，')}`}
        >
          {[0.25, 0.5, 0.75, 1].map((ratio) => (
            <polygon
              key={ratio}
              points={points
                .map((_, index) => {
                  const { x, y } = toPoint(index, ratio);
                  return `${x.toFixed(1)},${y.toFixed(1)}`;
                })
                .join(' ')}
              fill="none"
              stroke="var(--border)"
              strokeWidth={1}
            />
          ))}
          {points.map((_, index) => {
            const { x, y } = toPoint(index, 1);
            return (
              <line
                key={index}
                x1={center}
                y1={center}
                x2={x}
                y2={y}
                stroke="var(--border)"
                strokeWidth={1}
              />
            );
          })}
          <polygon points={polygon} fill="rgba(62,207,142,.22)" stroke="var(--accent)" strokeWidth={1.5} />
          {points.map((point, index) => {
            const { x, y } = toPoint(index, point.value / 100);
            return <circle key={point.label} cx={x} cy={y} r={2.5} fill="var(--accent)" />;
          })}
          {points.map((point, index) => {
            const { x, y } = toPoint(index, 1.18);
            return (
              <text
                key={`${point.label}-label`}
                x={x}
                y={y}
                textAnchor="middle"
                dominantBaseline="middle"
                fill="var(--text-muted)"
                fontSize={10}
              >
                {point.label}
                <tspan fill="var(--text-dim)" fontSize={9}>
                  {' '}
                  {Math.round(point.value)}
                </tspan>
              </text>
            );
          })}
        </svg>
      </div>
    </Card>
  );
}
