'use client';

import { Mic, Play, SkipForward } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { Badge, Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Field, InlineNote, Select, TextInput } from '@/components/ui/field';
import type { TtsProbeResponse } from '@/lib/api/types';
import type { TtsDraft } from '@/stores/setupWizard';

const VOICES = [
  { id: 'zh_female_wanwanxiaohe_moon_bigtts', label: '湾湾小何（女声 · 讲解向）' },
  { id: 'zh_male_beijingxiaoye_moon_bigtts', label: '北京小爷（男声 · 讲解向）' },
  { id: 'zh_female_shuangkuaisisi_moon_bigtts', label: '爽快思思（女声 · 轻快）' },
  { id: 'zh_male_yangguangqingnian_moon_bigtts', label: '阳光青年（男声 · 轻快）' },
];

const CLUSTERS = ['volcano_tts', 'volcano_icl', 'volcano_mega'];

export function TtsStep({
  enabled,
  tts,
  probe,
  probing,
  transportError,
  onToggle,
  onChange,
  onProbe,
  onSkipAll,
}: {
  enabled: boolean;
  tts: TtsDraft;
  probe: TtsProbeResponse | null;
  probing: boolean;
  transportError: { code: string; message: string; hint: string } | null;
  onToggle: (enabled: boolean) => void;
  onChange: (patch: Partial<TtsDraft>) => void;
  onProbe: () => void;
  onSkipAll: () => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewEnded, setPreviewEnded] = useState(false);

  // "试听 3 秒样例" — play at most 3 seconds, then stop (spec §3.6.2 S3).
  useEffect(() => {
    if (!previewing) return;
    const timer = window.setTimeout(() => {
      audioRef.current?.pause();
      setPreviewing(false);
      setPreviewEnded(true);
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [previewing]);

  const sampleUrl = probe?.ok ? probe.sample_audio_url : null;

  return (
    <div className="space-y-4">
      <InlineNote>
        语音是可选的：不配置也能完课，播放器会自动切换成“字幕自动推进”模式（4.2 字/秒），学习体验不受影响。
      </InlineNote>

      <label className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface px-3 py-2">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => onToggle(event.target.checked)}
          className="size-4 accent-[var(--accent)]"
        />
        <span className="text-xs text-text">启用豆包 / 火山引擎 TTS 配音</span>
        <Badge tone={enabled ? 'accent' : 'muted'} className="ml-auto">
          {enabled ? '将合成讲解音频' : '跳过 · 字幕模式'}
        </Badge>
      </label>

      {enabled ? (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="App ID" htmlFor="tts-app-id" required hint="火山引擎控制台 → 语音技术 → 应用管理">
              <TextInput
                id="tts-app-id"
                value={tts.app_id}
                onChange={(event) => onChange({ app_id: event.target.value })}
                placeholder="你的 appid"
                spellCheck={false}
              />
            </Field>
            <Field label="Access Token" htmlFor="tts-token" required>
              <TextInput
                id="tts-token"
                type="password"
                value={tts.access_token}
                onChange={(event) => onChange({ access_token: event.target.value })}
                placeholder="access_token"
                autoComplete="off"
              />
            </Field>
            <Field label="集群" htmlFor="tts-cluster" hint="默认 volcano_tts">
              <Select
                id="tts-cluster"
                value={tts.cluster}
                onChange={(event) => onChange({ cluster: event.target.value })}
              >
                {CLUSTERS.map((cluster) => (
                  <option key={cluster} value={cluster}>
                    {cluster}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="音色" htmlFor="tts-voice">
              <Select
                id="tts-voice"
                value={tts.voice_type}
                onChange={(event) => onChange({ voice_type: event.target.value })}
              >
                {VOICES.map((voice) => (
                  <option key={voice.id} value={voice.id}>
                    {voice.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              onClick={onProbe}
              loading={probing}
              icon={<Mic className="size-4" aria-hidden />}
            >
              {probing ? '正在合成…' : '合成 3 秒样例'}
            </Button>
            {sampleUrl ? (
              <Button
                variant="outline"
                onClick={() => {
                  setPreviewEnded(false);
                  setPreviewing(true);
                  void audioRef.current?.play().catch(() => setPreviewing(false));
                }}
                icon={<Play className="size-3.5" aria-hidden />}
              >
                {previewing ? '试听中（最多 3 秒）' : '试听'}
              </Button>
            ) : null}
            <Button variant="ghost" onClick={onSkipAll} icon={<SkipForward className="size-3.5" aria-hidden />}>
              跳过
            </Button>
          </div>

          {sampleUrl ? (
            <Card className="space-y-2">
              <audio
                ref={audioRef}
                src={sampleUrl}
                preload="auto"
                className="w-full"
                onEnded={() => {
                  setPreviewing(false);
                  setPreviewEnded(true);
                }}
              />
              <p className="text-[11px] text-text-dim">
                {previewEnded ? '样例播放结束（已按 3 秒截断试听）。' : '合成的样例音频来自 /api/objects/audio/…'}
              </p>
            </Card>
          ) : null}

          {probe && !probe.ok ? (
            <Card className="border-warn/40 bg-warn/5">
              <p className="text-xs font-medium text-warn">
                TTS 合成失败{probe.error ? ` · ${probe.error.code}` : ''}
              </p>
              {probe.error?.message ? (
                <p className="mt-1 text-xs text-text-muted">{probe.error.message}</p>
              ) : null}
              {probe.error?.hint ? (
                <p className="mt-1 text-[11px] text-text-dim">{probe.error.hint}</p>
              ) : null}
              <p className="mt-2 text-[11px] text-text-dim">
                可以直接跳过：课程会在没有音频的情况下按字幕推进。
              </p>
            </Card>
          ) : null}

          {transportError ? (
            <Card className="border-danger/40 bg-danger/5">
              <p className="text-xs font-medium text-danger">样例请求失败 · {transportError.code}</p>
              <p className="mt-1 text-xs text-text-muted">{transportError.message}</p>
              <p className="mt-1 text-[11px] text-text-dim">{transportError.hint}</p>
            </Card>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
