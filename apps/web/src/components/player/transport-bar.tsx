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
        data-rl-tap=""
        className="rounded-[var(--radius-sm)] border border-border bg-code-bg px-1.5 text-[11px] text-text max-lg:h-[var(--tap-target)] lg:py-1"
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

/**
 * Player transport bar — spec §3.3.1 (断点契约) / §7.3 T-TOUCH-4.
 *
 * Layout: `base` is two rows (buttons, then a full-width progress row); `sm` and
 * up is the familiar single row. The reason is not aesthetics: at 390px the
 * scrubber squeezed between the buttons shrinks to ~60px for a 6-minute lesson,
 * which nobody can aim at — it reads as "the progress bar is broken".
 *
 * Hit areas: every primary action carries `data-rl-tap` and is ≥44×44 below `lg`.
 * `lg` restores the original 32px density, because a mouse does not need 44px and
 * turning every tool button into a 44px block makes the bar a wall (§3.3.1).
 *
 * 尺寸必须写成 `h-[var(--tap-target)]` 而不是 `h-11`：`html { font-size: 14px }`，
 * 于是 Tailwind 的 `0.25rem` 在这里是 3.5px，`h-11` 只有 38.5px —— 一个看起来
 * 完全正确、实测差 5.5px 的命中区。文案里"44px"的唯一真源是 `--tap-target`。
 */
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
    <div
      className="border-t border-border bg-bg-elevated"
      // 稳定钩子：a11y / mobile 门禁用它定位"播放器工具条"这块我们自己的子树
      data-rl-transport=""
      // 安全区：iPhone 的手势条会压在最后一行按钮上，用 env() 把内容顶上去（§3.3.1）
      style={{ paddingBottom: 'var(--safe-bottom)' }}
    >
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-2 px-3 py-2">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            data-rl-tap=""
            className="max-lg:h-[var(--tap-target)] max-lg:w-[var(--tap-target)]"
            onClick={prevStep}
            aria-label="上一步"
            disabled={stepIndex === 0}
          >
            <ChevronLeft className="size-4" aria-hidden />
          </Button>
          <Button
            variant="primary"
            size="sm"
            data-rl-tap=""
            onClick={togglePlay}
            aria-label={isPlaying ? '暂停' : '播放'}
            className="rounded-full p-0 max-lg:h-[var(--tap-target)] max-lg:w-[var(--tap-target)] lg:size-9"
          >
            {isPlaying ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            data-rl-tap=""
            className="max-lg:h-[var(--tap-target)] max-lg:w-[var(--tap-target)]"
            onClick={nextStep}
            aria-label="下一步"
            disabled={stepIndex >= timeline.steps.length - 1}
          >
            <ChevronRight className="size-4" aria-hidden />
          </Button>
        </div>

        {/*
          进度条：base 下 `order-last basis-full` 让它独占第二行；
          `sm` 起回到单行的中间弹性区。`min-w-0` 是 flex 子项能收缩的前提。
        */}
        <div className="order-last flex w-full basis-full items-center gap-2 sm:order-none sm:w-auto sm:basis-auto sm:flex-1">
          <span className="shrink-0 font-mono text-[11px] text-text-dim">{formatClock(positionMs)}</span>
          <input
            type="range"
            min={0}
            max={Math.max(1, duration)}
            step={100}
            value={Math.min(positionMs, duration)}
            onChange={(event) => seekStep(Number(event.target.value))}
            aria-label="当前步骤进度"
            className="h-1 min-w-0 flex-1 accent-[var(--accent)]"
          />
          <span className="shrink-0 font-mono text-[11px] text-text-dim">{formatClock(duration)}</span>
        </div>

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
            data-rl-tap=""
            className="max-lg:h-[var(--tap-target)] max-lg:w-[var(--tap-target)]"
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
          <Button
            variant="ghost"
            size="sm"
            data-rl-tap=""
            className="max-lg:h-[var(--tap-target)] max-lg:w-[var(--tap-target)]"
            onClick={() => toggleShortcuts()}
            aria-label="快捷键说明"
          >
            <Keyboard className="size-4" aria-hidden />
          </Button>
        </div>
      </div>

      {status === 'ended' ? (
        <div className="border-t border-border px-3 py-1.5 text-center text-[11px] text-accent">
          本节已看完 ·{' '}
          <button
            type="button"
            data-rl-tap=""
            className="px-2 underline underline-offset-2 max-lg:min-h-[var(--tap-target)]"
            onClick={togglePlay}
          >
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
