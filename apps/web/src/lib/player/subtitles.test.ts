import { describe, expect, it } from 'vitest';

import { activeCue, cueProgress, cuesFromSegments, splitIntoCues } from '@/lib/player/subtitles';
import type { TimelineSegment } from '@/lib/player/timeline';

function segment(id: string, text: string, start: number, end: number): TimelineSegment {
  return {
    id,
    text,
    startMs: start,
    endMs: end,
    focus: null,
    subtitleStyle: 'normal',
    boardActions: [],
  };
}

describe('subtitle cues', () => {
  it('splits a long sentence into readable lines without losing characters', () => {
    const text =
      '这里先把对话历史整理成模型可以消化的输入，然后再决定要不要调用工具，最后把结果拼成一条回复。';
    const cues = splitIntoCues(segment('s0', text, 0, 8000));
    expect(cues.length).toBeGreaterThan(1);
    expect(cues.map((cue) => cue.text).join('')).toBe(text);
    expect(cues[0]?.startMs).toBe(0);
    expect(cues[cues.length - 1]?.endMs).toBe(8000);
  });

  it('distributes timing proportionally and keeps it monotonic', () => {
    const cues = cuesFromSegments([segment('s0', '短句。这一句明显要长得多，因为它包含更多文字内容。', 0, 6000)]);
    for (let index = 1; index < cues.length; index += 1) {
      expect(cues[index]!.startMs).toBeGreaterThanOrEqual(cues[index - 1]!.endMs - 1);
    }
  });

  it('locates the active cue at every boundary', () => {
    const cues = cuesFromSegments([segment('s0', '第一句。第二句。', 0, 4000)]);
    expect(activeCue(cues, 0)?.index).toBe(0);
    expect(activeCue(cues, 4000)?.index).toBe(cues.length - 1);
    expect(activeCue(cues, -10)?.index).toBe(0);
    expect(activeCue([], 0)).toBeNull();
  });

  it('reports cue progress between 0 and 1', () => {
    const cue = splitIntoCues(segment('s0', '一句话', 1000, 3000))[0]!;
    expect(cueProgress(cue, 1000)).toBe(0);
    expect(cueProgress(cue, 2000)).toBeCloseTo(0.5, 1);
    expect(cueProgress(cue, 5000)).toBe(1);
  });
});
