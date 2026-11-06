/**
 * Subtitle segmentation — spec §5.3 / §7.3.
 *
 * The backend ships narration segments that cover `[0, duration]`. On screen a
 * single segment is still too long for one line, so the view splits it into
 * display cues without touching the authoritative timing.
 */

import type { TimelineSegment } from '@/lib/player/timeline';

export interface SubtitleCue {
  id: string;
  segmentId: string;
  text: string;
  startMs: number;
  endMs: number;
  /** 0-based index inside the parent segment. */
  index: number;
  total: number;
}

const MAX_CHARS_PER_LINE = 42;

/**
 * Splits text on sentence punctuation, then greedily packs pieces into lines of
 * at most ~42 chars. Timing is distributed proportionally to character count so
 * a long sentence does not flash for the same duration as a short one.
 */
export function splitIntoCues(segment: TimelineSegment): SubtitleCue[] {
  const text = segment.text.trim();
  if (!text) {
    return [
      {
        id: `${segment.id}-0`,
        segmentId: segment.id,
        text: '',
        startMs: segment.startMs,
        endMs: segment.endMs,
        index: 0,
        total: 1,
      },
    ];
  }

  const pieces = text
    .split(/(?<=[。！？；!?;])\s*/u)
    .flatMap((sentence) => chunkSentence(sentence))
    .filter((piece) => piece.length > 0);

  const safePieces = pieces.length > 0 ? pieces : [text];
  const totalChars = safePieces.reduce((sum, piece) => sum + piece.length, 0) || 1;
  const span = Math.max(segment.endMs - segment.startMs, safePieces.length * 300);

  let cursor = segment.startMs;
  return safePieces.map((piece, index) => {
    const isLast = index === safePieces.length - 1;
    const duration = isLast
      ? Math.max(segment.endMs - cursor, 200)
      : Math.round((piece.length / totalChars) * span);
    const startMs = cursor;
    const endMs = isLast ? Math.max(segment.endMs, startMs + 200) : startMs + Math.max(duration, 200);
    cursor = endMs;
    return {
      id: `${segment.id}-${index}`,
      segmentId: segment.id,
      text: piece,
      startMs,
      endMs,
      index,
      total: safePieces.length,
    };
  });
}

function chunkSentence(sentence: string): string[] {
  const trimmed = sentence.trim();
  if (!trimmed) return [];
  if (trimmed.length <= MAX_CHARS_PER_LINE) return [trimmed];
  const chunks: string[] = [];
  let rest = trimmed;
  while (rest.length > MAX_CHARS_PER_LINE) {
    const window = rest.slice(0, MAX_CHARS_PER_LINE);
    // Prefer breaking after a clause mark, then an ASCII space.
    const breakAt = Math.max(
      window.lastIndexOf('，'),
      window.lastIndexOf(','),
      window.lastIndexOf(' '),
    );
    const cut = breakAt > MAX_CHARS_PER_LINE / 2 ? breakAt + 1 : MAX_CHARS_PER_LINE;
    chunks.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) chunks.push(rest);
  return chunks;
}

export function cuesFromSegments(segments: TimelineSegment[]): SubtitleCue[] {
  return segments.flatMap(splitIntoCues);
}

/** Cue visible at `ms`, boundary-safe (t=0 → first, t=end → last). */
export function activeCue(cues: SubtitleCue[], ms: number): SubtitleCue | null {
  if (cues.length === 0) return null;
  const first = cues[0]!;
  if (ms <= first.startMs) return first;
  const last = cues[cues.length - 1]!;
  if (ms >= last.endMs) return last;

  let low = 0;
  let high = cues.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const cue = cues[mid]!;
    if (ms < cue.startMs) high = mid - 1;
    else if (ms >= cue.endMs) low = mid + 1;
    else return cue;
  }
  return cues[Math.min(Math.max(high, 0), cues.length - 1)] ?? null;
}

/** How far through the cue we are, used for a soft "words lighting up" effect. */
export function cueProgress(cue: SubtitleCue, ms: number): number {
  const span = cue.endMs - cue.startMs;
  if (span <= 0) return 1;
  return Math.min(Math.max((ms - cue.startMs) / span, 0), 1);
}
