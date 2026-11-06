'use client';

/**
 * SSE client — spec §7.5.
 *
 * `fetch` + `ReadableStream` instead of `EventSource`, because EventSource
 * cannot send `X-CSRF-Token`, cannot set custom headers, and cannot reliably
 * set `Last-Event-ID` in every browser.
 *
 * Behaviour contract:
 *  - exponential reconnect 1/2/4/8/16s, max 5 attempts;
 *  - resume with `Last-Event-ID: <last seq>` (monotonic, from the frame id);
 *  - unknown `type` → console.warn and keep reading (§5.5 rule 3);
 *  - `job.snapshot` → re-sync with `GET <snapshotUrl>` before continuing;
 *  - reconnect is paused while the document is hidden, resumed on visibility.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { openEventStream } from '@/lib/api/client';
import {
  createSseDecoder,
  KNOWN_EVENT_TYPES,
  toEnvelope,
  type EnvelopeEvent,
} from '@/lib/sse/parse';

export type StreamStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error';

const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000];
const TERMINAL_TYPES = new Set(['job.completed', 'job.failed']);

export interface UseEventStreamOptions {
  /** Same-origin stream URL, e.g. `/api/sse/jobs/job_123`. `null` disables. */
  url: string | null;
  enabled?: boolean;
  jobId?: string;
  /** JSON snapshot endpoint used to recover after `job.snapshot`. */
  snapshotUrl?: string | null;
  onEvent?: (event: EnvelopeEvent) => void;
  onSnapshot?: (snapshot: unknown, event: EnvelopeEvent) => void;
  maxRetries?: number;
}

export interface UseEventStreamResult {
  status: StreamStatus;
  lastSeq: number;
  attempts: number;
  error: Error | null;
  /** Manual reconnect (the "重试" button). Resets the backoff counter. */
  reconnect: () => void;
  close: () => void;
}

export function useEventStream(options: UseEventStreamOptions): UseEventStreamResult {
  const {
    url,
    enabled = true,
    jobId,
    snapshotUrl = null,
    onEvent,
    onSnapshot,
    maxRetries = 5,
  } = options;

  const [status, setStatus] = useState<StreamStatus>('idle');
  const [attempts, setAttempts] = useState(0);
  const [error, setError] = useState<Error | null>(null);
  const [lastSeqState, setLastSeq] = useState(0);

  const handlers = useRef({ onEvent, onSnapshot });
  handlers.current = { onEvent, onSnapshot };

  const lastSeqRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptsRef = useRef(0);
  const closedByTerminal = useRef(false);
  const runIdRef = useRef(0);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const syncSnapshot = useCallback(async (event: EnvelopeEvent) => {
    if (!snapshotUrl) return;
    try {
      const response = await fetch(snapshotUrl, {
        headers: { accept: 'application/json' },
        cache: 'no-store',
        credentials: 'same-origin',
      });
      if (!response.ok) return;
      const snapshot: unknown = await response.json();
      handlers.current.onSnapshot?.(snapshot, event);
    } catch (snapshotError) {
      // A failed snapshot re-sync is not fatal: the stream keeps flowing and
      // the next `job.phase` event will rebuild the UI from progress anyway.
      console.warn('[sse] snapshot re-sync failed', snapshotError);
    }
  }, [snapshotUrl]);

  const connect = useCallback(async () => {
    if (!url || !enabled) return;
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
      setStatus('reconnecting');
      return;
    }

    clearTimer();
    const runId = ++runIdRef.current;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setStatus(attemptsRef.current === 0 ? 'connecting' : 'reconnecting');

    let receivedFrame = false;
    const decoder = createSseDecoder();

    const scheduleRetry = (reason: Error | null) => {
      if (runId !== runIdRef.current || controller.signal.aborted) return;
      if (closedByTerminal.current) {
        setStatus('closed');
        return;
      }
      if (attemptsRef.current >= maxRetries) {
        setStatus('error');
        setError(reason ?? new Error('事件流已断开，重连次数用尽。'));
        return;
      }
      if (typeof document !== 'undefined' && document.hidden) {
        // Paused while hidden: wait for visibilitychange instead of burning
        // through the retry budget in a background tab.
        setStatus('reconnecting');
        return;
      }
      const delay = BACKOFF_MS[Math.min(attemptsRef.current, BACKOFF_MS.length - 1)] ?? 16000;
      attemptsRef.current += 1;
      setAttempts(attemptsRef.current);
      setStatus('reconnecting');
      if (reason) setError(reason);
      clearTimer();
      timerRef.current = setTimeout(() => {
        void connect();
      }, delay);
    };

    try {
      const response = await openEventStream(url, {
        signal: controller.signal,
        lastEventId: lastSeqRef.current > 0 ? lastSeqRef.current : null,
      });

      const body = response.body;
      if (!body) {
        scheduleRetry(new Error('事件流没有响应体。'));
        return;
      }

      setStatus('open');
      const reader = body.getReader();
      const textDecoder = new TextDecoder();

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done || runId !== runIdRef.current) break;
        const chunk = textDecoder.decode(value, { stream: true });
        for (const frame of decoder.push(chunk)) {
          const envelope = toEnvelope(frame, jobId);
          if (!envelope) continue;
          receivedFrame = true;
          if (envelope.seq > lastSeqRef.current) {
            lastSeqRef.current = envelope.seq;
            setLastSeq(envelope.seq);
          }
          if (envelope.type === 'job.snapshot') {
            void syncSnapshot(envelope);
          }
          if (!KNOWN_EVENT_TYPES.has(envelope.type)) {
            // Forward compatibility: log and continue, never kill the stream.
            console.warn('[sse] ignoring unknown event type', envelope.type, envelope.data);
            continue;
          }
          handlers.current.onEvent?.(envelope);
          if (TERMINAL_TYPES.has(envelope.type)) {
            closedByTerminal.current = true;
            break;
          }
        }
        if (closedByTerminal.current) break;
      }

      if (closedByTerminal.current) {
        setStatus('closed');
        return;
      }
      if (runId !== runIdRef.current) return;
      scheduleRetry(null);
    } catch (streamError) {
      if (controller.signal.aborted) return;
      const normalized =
        streamError instanceof Error ? streamError : new Error('事件流连接失败。');
      if (receivedFrame) {
        // A frame arrived, so the transport works; this disconnect is a gap.
        attemptsRef.current = Math.min(attemptsRef.current, 1);
      }
      scheduleRetry(normalized);
    }
  }, [clearTimer, enabled, jobId, maxRetries, syncSnapshot, url]);

  useEffect(() => {
    if (!url || !enabled) {
      setStatus('idle');
      return;
    }
    closedByTerminal.current = false;
    attemptsRef.current = 0;
    setAttempts(0);
    setError(null);
    lastSeqRef.current = 0;
    setLastSeq(0);
    void connect();

    const onVisibility = () => {
      if (typeof document === 'undefined') return;
      if (!document.hidden && !closedByTerminal.current) {
        // Re-arm immediately: the user is back and expects live progress.
        clearTimer();
        attemptsRef.current = Math.min(attemptsRef.current, 1);
        void connect();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      runIdRef.current += 1;
      abortRef.current?.abort();
      abortRef.current = null;
      clearTimer();
    };
    // `connect` is intentionally the only dependency: it is rebuilt when the
    // url/jobId/handlers change, which is exactly when we want a fresh stream.
  }, [url, enabled, connect, clearTimer]);

  const reconnect = useCallback(() => {
    closedByTerminal.current = false;
    attemptsRef.current = 0;
    setAttempts(0);
    setError(null);
    void connect();
  }, [connect]);

  const close = useCallback(() => {
    closedByTerminal.current = true;
    runIdRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    clearTimer();
    setStatus('closed');
  }, [clearTimer]);

  return { status, lastSeq: lastSeqState, attempts, error, reconnect, close };
}
