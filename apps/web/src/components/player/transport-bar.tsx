'use client';

import {
  Captions,
  CaptionsOff,
  ChevronLeft,
  ChevronRight,
  Keyboard,
  Pause,
  Play,
  RotateCcw,
  Volume2,
} from 'lucide-react';
import { useEffect, useState } from 'react';

import { Badge } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Overlay } from '@/components/ui/overlay';
import { usePlayerEngine } from '@/components/player/player-provider';
import { usePlayerStore } from '@/stores/player';
import { SPEED_OPTIONS, formatClock } from '@/lib/player/timeline';
import { cn } from '@/lib/utils';

const SHORTCUTS = [
  ['Space', '播放 / 暂停'],
  ['← / →', '后退 / 前进 5 秒'],
  ['J / K', '上一步 / 下一步'],
  ['C', '显示 / 隐藏字幕'],
  ['[ / ]', '降低 / 提高倍速'],
  ['?', '打开这个快捷键面板'],
];

export function SpeedMenu() {
  const speed = usePlayerStore((state) => state.speed);
  const setSpeed = usePlayerStore((state) => state.setSpeed);
  return (
    <label className="inline-flex items-center gap-1 text-[11px] text-text-muted">
      <span className="sr-only">播放速度</span>
      <select
        value={speed}
        onChange={(event) => setSpeed(Number(event.target.value) as (typeof SPEED_OPTIONS)[number])}
        className="rounded-[var(--radius-sm)] border border-border bg-code-bg px-1.5 py-1 text-[11px] text-text"
      >
        {SPEED_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {option.toFixed(2).replace(/0$/, '')}×
          </option>
        ))}
      </select>
    </label>
  );
}

export function TransportBar() {
  const engine = usePlayerEngine();
  const status = usePlayerStore((state) => state.status);
  const stepIndex = usePlayerStore((state) => state.stepIndex);
  const positionMs = usePlayerStore((state) => state.positionMs);
  const timeline = usePlayerStore((state) => state.timeline);
  const captionsOn = usePlayerStore((state) => state.captionsOn);
  const simulationOnly = usePlayerStore((state) => state.simulationOnly);
  const shortcutsOpen = usePlayerStore((state) => state.shortcutsOpen);
  const togglePlay = usePlayerStore((state) => state.togglePlay);
  const nextStep = usePlayerStore((state) => state.nextStep);
  const prevStep = usePlayerStore((state) => state.prevStep);
  const seekStep = usePlayerStore((state) => state.seekStep);
  const toggleCaptions = usePlayerStore((state) => state.toggleCaptions);
  const toggleShortcuts = usePlayerStore((state) => state.toggleShortcuts);

  const [volume, setVolume] = useState(1);
  useEffect(() => {
    engine.setVolume(volume);
  }, [volume, engine]);

  const step = timeline.steps[stepIndex];
  const duration = step?.durationMs ?? 0;
  const isPlaying = status === 'playing';

  if (timeline.steps.length === 0) {
    return (
      <div className="border-t border-border bg-bg-elevated px-4 py-2 text-center text-[11px] text-text-dim">
        本层还没有可播放的讲解。切换到左侧大纲里的其它课时试试。
      </div>
    );
  }

  return (
    <div className="border-t border-border bg-bg-elevated">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-2 px-3 py-2">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={prevStep}
            aria-label="上一步"
            disabled={stepIndex === 0}
          >
            <ChevronLeft className="size-4" aria-hidden />
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={togglePlay}
            aria-label={isPlaying ? '暂停' : '播放'}
            className="size-9 rounded-full p-0"
          >
            {isPlaying ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={nextStep}
            aria-label="下一步"
            disabled={stepIndex >= timeline.steps.length - 1}
          >
            <ChevronRight className="size-4" aria-hidden />
          </Button>
        </div>

        <span className="shrink-0 font-mono text-[11px] text-text-dim">{formatClock(positionMs)}</span>
        <input
          type="range"
          min={0}
          max={Math.max(1, duration)}
          step={100}
          value={Math.min(positionMs, duration)}
          onChange={(event) => seekStep(Number(event.target.value))}
          aria-label="当前步骤进度"
          className="h-1 min-w-[80px] flex-1 accent-[var(--accent)]"
        />
        <span className="shrink-0 font-mono text-[11px] text-text-dim">{formatClock(duration)}</span>

        <span className="hidden shrink-0 items-center gap-1 text-[11px] text-text-muted sm:flex">
          <span className="font-mono text-text">
            {stepIndex + 1}/{timeline.steps.length}
          </span>
          <span className="max-w-[180px] truncate">{step?.title}</span>
        </span>

        <div className="ml-auto flex items-center gap-1.5">
          {simulationOnly ? (
            <Badge tone="warn" title="本节包含无音频的估算推进或教学模拟步骤">
              教学模拟 · 字幕推进
            </Badge>
          ) : null}
          <Button
            variant="ghost"
            size="sm"
            onClick={toggleCaptions}
            aria-pressed={captionsOn}
            aria-label={captionsOn ? '隐藏字幕' : '显示字幕'}
          >
            {captionsOn ? <Captions className="size-4" aria-hidden /> : <CaptionsOff className="size-4" aria-hidden />}
          </Button>
          <SpeedMenu />
          <label className="hidden items-center gap-1 text-text-dim md:flex">
            <Volume2 className="size-3.5" aria-hidden />
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={volume}
              onChange={(event) => setVolume(Number(event.target.value))}
              aria-label="音量"
              className="h-1 w-16 accent-[var(--accent)]"
            />
          </label>
          <Button variant="ghost" size="sm" onClick={() => toggleShortcuts()} aria-label="快捷键说明">
            <Keyboard className="size-4" aria-hidden />
          </Button>
        </div>
      </div>

      {status === 'ended' ? (
        <div className="border-t border-border px-3 py-1.5 text-center text-[11px] text-accent">
          本节已看完 ·{' '}
          <button type="button" className="underline underline-offset-2" onClick={togglePlay}>
            <RotateCcw className="mr-1 inline size-3" aria-hidden />
            重看
          </button>
        </div>
      ) : null}

      <Overlay
        open={shortcutsOpen}
        onClose={() => toggleShortcuts(false)}
        title="快捷键"
        variant="dialog"
      >
        <ul className="divide-y divide-border">
          {SHORTCUTS.map(([keys, description]) => (
            <li key={keys} className="flex items-center justify-between py-2 text-xs">
              <kbd className="rounded border border-border bg-code-bg px-1.5 py-0.5 font-mono text-[11px] text-text">
                {keys}
              </kbd>
              <span className="text-text-muted">{description}</span>
            </li>
          ))}
        </ul>
        <p className={cn('mt-3 text-[11px] text-text-dim')}>
          焦点在代码编辑器里时，快捷键让位给编辑器（避免与 Monaco 的按键冲突）。
        </p>
      </Overlay>
    </div>
  );
}
