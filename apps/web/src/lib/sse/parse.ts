/**
 * SSE frame parser shared by `useEventStream` and the inline-question stream.
 *
 * Frame shape (spec §5.5): `id: <seq>\nevent: <type>\ndata: <json>\n\n`, with
 * `: keepalive` comment frames every 15s. Parsing is incremental so partial
 * frames survive chunk boundaries.
 */

export interface ParsedEvent {
  /** `id:` — the monotonic seq used for `Last-Event-ID` resume. */
  id?: string;
  /** `event:` — the event `type`. */
  event?: string;
  /** Concatenated `data:` lines. */
  data: string;
  /** Raw frame text, useful for debugging unknown types. */
  raw: string;
}

/** Event types the frontend understands (§5.5 table). */
export const KNOWN_EVENT_TYPES = new Set([
  'system.init',
  'agent.thinking',
  'agent.text.delta',
  'tool.start',
  'tool.end',
  'step.delta',
  'question.delta',
  'question.completed',
  'job.phase',
  'node.completed',
  'job.snapshot',
  'job.completed',
  'job.failed',
  'run.completed',
  'budget.exceeded',
]);

export function parseFrame(raw: string): ParsedEvent | null {
  const lines = raw.split('\n');
  let id: string | undefined;
  let event: string | undefined;
  const dataLines: string[] = [];

  for (const rawLine of lines) {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
    if (!line || line.startsWith(':')) continue;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '');
    if (field === 'id') id = value;
    else if (field === 'event') event = value;
    else if (field === 'data') dataLines.push(value);
  }

  if (dataLines.length === 0 && !event && !id) return null;
  return { id, event, data: dataLines.join('\n'), raw };
}

/**
 * Stateful decoder: feed it decoded text chunks, get complete frames back.
 * `flush()` emits a trailing frame that was never terminated by a blank line
 * (some proxies close the stream without a final `\n\n`).
 */
export function createSseDecoder(): {
  push: (chunk: string) => ParsedEvent[];
  flush: () => ParsedEvent | null;
} {
  let buffer = '';

  const drain = (): ParsedEvent[] => {
    const events: ParsedEvent[] = [];
    let separator = buffer.indexOf('\n\n');
    while (separator !== -1) {
      const frame = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);
      const parsed = parseFrame(frame);
      if (parsed) events.push(parsed);
      separator = buffer.indexOf('\n\n');
    }
    return events;
  };

  return {
    push(chunk: string) {
      buffer += chunk;
      return drain();
    },
    flush() {
      const rest = buffer.trim();
      buffer = '';
      return rest ? parseFrame(rest) : null;
    },
  };
}

export interface EnvelopeEvent<T = Record<string, unknown>> {
  type: string;
  seq: number;
  ts: number;
  schemaVersion: number;
  jobId?: string | null;
  runId?: string | null;
  data: T;
  /** Frame id, which is authoritative for resume if `data.seq` is missing. */
  id?: string;
}

/**
 * Turns a parsed frame into a typed envelope. Unknown event types are returned
 * with `type` intact so the caller can log-and-continue (§5.5 rule 3) instead
 * of aborting the read loop.
 */
export function toEnvelope(event: ParsedEvent, fallbackJobId?: string): EnvelopeEvent | null {
  let payload: Record<string, unknown> = {};
  if (event.data) {
    try {
      const parsed: unknown = JSON.parse(event.data);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        payload = parsed as Record<string, unknown>;
      }
    } catch {
      // A malformed frame must not kill the stream.
      return null;
    }
  }

  const type = (typeof payload.type === 'string' ? payload.type : event.event) ?? '';
  if (!type) return null;

  const seqValue =
    typeof payload.seq === 'number'
      ? payload.seq
      : Number.parseInt(event.id ?? '', 10);
  const seq = Number.isFinite(seqValue) ? seqValue : 0;
  const ts = typeof payload.ts === 'number' ? payload.ts : Date.now();
  const schemaVersion = typeof payload.schemaVersion === 'number' ? payload.schemaVersion : 1;
  const data =
    payload.data && typeof payload.data === 'object' && !Array.isArray(payload.data)
      ? (payload.data as Record<string, unknown>)
      : {};

  return {
    type,
    seq,
    ts,
    schemaVersion,
    jobId: typeof payload.jobId === 'string' ? payload.jobId : fallbackJobId,
    runId: typeof payload.runId === 'string' ? payload.runId : null,
    data,
    id: event.id,
  };
}
