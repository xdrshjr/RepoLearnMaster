'use client';

/**
 * Player engine — spec §7.3.
 *
 * Owns the single time source:
 *  - with audio → `audio.currentTime`;
 *  - without audio → `performance.now() - startedAt`, advancing at the estimated
 *    rate baked into the timeline (4.2 chars/second, §3.8).
 *
 * Subtitles, code highlight and board actions all read the store; nothing else
 * keeps its own clock. Playback speed only touches `playbackRate`.
 *
 * Progress is PUT every 2s, plus one `sendBeacon` on visibilitychange/beforeunload
 * (§7.3 rule 4) so closing the tab does not lose the position.
 */

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';

import { currentStepDuration, usePlayerStore } from '@/stores/player';
import { nextSpeed, previousSpeed } from '@/lib/player/timeline';
import { ensureCsrfToken } from '@/lib/api/client';
import { CSRF_HEADER } from '@/lib/api/constants';

interface PlayerEngine {
  audioRef: React.RefObject<HTMLAudioElement | null>;
  volume: number;
  setVolume: (value: number) => void;
}

const PlayerContext = createContext<PlayerEngine | null>(null);

const TICK_INTERVAL_MS = 90;
const PROGRESS_INTERVAL_MS = 2000;

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.closest('.monaco-editor')) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

export function PlayerProvider({
  courseId,
  children,
}: {
  courseId: string;
  children: ReactNode;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [volume, setVolumeState] = useState(1);
  const startedAtRef = useRef<number>(performance.now());
  const basePositionRef = useRef<number>(0);
  const lastTickRef = useRef<number>(performance.now());
  const lastProgressAtRef = useRef<number>(0);

  const status = usePlayerStore((state) => state.status);
  const stepIndex = usePlayerStore((state) => state.stepIndex);
  const bundle = usePlayerStore((state) => state.bundle);
  const audioUrl = usePlayerStore(
    (state) => state.timeline.steps[state.stepIndex]?.audioUrl ?? null,
  );

  const persist = useCallback(
    (useBeacon = false) => {
      const state = usePlayerStore.getState();
      const lessonKey = state.bundle?.lesson.key;
      if (!lessonKey) return;
      const step = state.timeline.steps[state.stepIndex];
      if (!step) return;
      const stepPercent = step.durationMs > 0 ? state.positionMs / step.durationMs : 0;
      const total = state.timeline.steps.length || 1;
      const percent = Math.round(((state.stepIndex + stepPercent) / total) * 100);
      const body = {
        lesson_key: lessonKey,
        step_index: state.stepIndex,
        position_ms: Math.round(state.positionMs),
        percent,
      };

      if (useBeacon && typeof navigator !== 'undefined' && 'sendBeacon' in navigator) {
        // text/plain is the only beacon content type that needs no preflight (§5.2).
        const payload = new Blob([JSON.stringify(body)], { type: 'text/plain;charset=UTF-8' });
        navigator.sendBeacon(`/api/courses/${encodeURIComponent(state.courseId ?? courseId)}/progress/beacon`, payload);
        return;
      }

      void fetch(`/api/courses/${encodeURIComponent(state.courseId ?? courseId)}/progress`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json', [CSRF_HEADER]: ensureCsrfToken() },
        body: JSON.stringify(body),
        keepalive: true,
        credentials: 'same-origin',
      }).catch(() => {
        // Progress is best-effort: a failed PUT must never interrupt playback.
      });
    },
    [courseId],
  );

  /* ---------------------------------------------------------------- clock */

  useEffect(() => {
    let frame = 0;
    let cancelled = false;

    const tick = () => {
      if (cancelled) return;
      frame = window.setTimeout(tick, TICK_INTERVAL_MS);
      const state = usePlayerStore.getState();
      const step = state.timeline.steps[state.stepIndex];
      if (!step) return;
      if (state.status !== 'playing') {
        basePositionRef.current = state.positionMs;
        lastTickRef.current = performance.now();
        return;
      }

      const now = performance.now();
      lastTickRef.current = now;

      const audio = audioRef.current;
      let position = state.positionMs;

      if (audio && Number.isFinite(audio.currentTime) && step.audioUrl) {
        position = audio.currentTime * 1000;
      } else {
        position = basePositionRef.current + (now - startedAtRef.current) * state.speed;
      }

      if (position >= step.durationMs) {
        const isLast = state.stepIndex >= state.timeline.steps.length - 1;
        if (isLast) {
          state.setPosition(step.durationMs);
          state.setStatus('ended');
          persist(false);
          return;
        }
        // Carry the overflow into the next step so the narration stays smooth.
        const overflow = position - step.durationMs;
        state.setStep(state.stepIndex + 1, overflow);
        const next = usePlayerStore.getState();
        basePositionRef.current = next.positionMs;
        startedAtRef.current = performance.now();
        lastTickRef.current = performance.now();
        return;
      }

      state.setPosition(position);
      basePositionRef.current = position;

      const nowMs = Date.now();
      if (nowMs - lastProgressAtRef.current > PROGRESS_INTERVAL_MS) {
        lastProgressAtRef.current = nowMs;
        persist(false);
      }
    };

    frame = window.setTimeout(tick, TICK_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(frame);
    };
  }, [persist]);

  // A play/pause transition re-bases the estimated clock.
  useEffect(() => {
    basePositionRef.current = usePlayerStore.getState().positionMs;
    startedAtRef.current = performance.now();
    lastTickRef.current = performance.now();
  }, [status]);

  /* ---------------------------------------------------------------- audio */

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (!audioUrl) {
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      return;
    }
    if (audio.src !== new URL(audioUrl, window.location.origin).toString()) {
      audio.src = audioUrl;
      audio.load();
    }
  }, [audioUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (status === 'playing') {
      audio.playbackRate = usePlayerStore.getState().speed;
      void audio.play().catch(() => {
        // Autoplay can be blocked; the user still gets the subtitle timeline.
        usePlayerStore.getState().setStatus('paused');
      });
    } else {
      audio.pause();
    }
  }, [status]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const speed = usePlayerStore.getState().speed;
    audio.playbackRate = speed;
    const unsubscribe = usePlayerStore.subscribe((state, previous) => {
      if (state.speed !== previous.speed) audio.playbackRate = state.speed;
      if (
        Math.abs(state.positionMs - previous.positionMs) > 400 &&
        Number.isFinite(audio.duration)
      ) {
        // A jump (scrub / architecture node click) must also move the audio.
        audio.currentTime = state.positionMs / 1000;
      }
    });
    return unsubscribe;
  }, []);

  /* ------------------------------------------------------------ shortcuts */

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (isEditableTarget(event.target)) return;
      const state = usePlayerStore.getState();
      if (state.timeline.steps.length === 0) return;

      switch (event.code) {
        case 'Space':
          event.preventDefault();
          state.togglePlay();
          break;
        case 'ArrowLeft':
          event.preventDefault();
          state.nudge(-5000);
          break;
        case 'ArrowRight':
          event.preventDefault();
          state.nudge(5000);
          break;
        case 'KeyK':
          event.preventDefault();
          state.nextStep();
          break;
        case 'KeyJ':
          event.preventDefault();
          state.prevStep();
          break;
        case 'KeyC':
          state.toggleCaptions();
          break;
        case 'BracketLeft':
          state.setSpeed(previousSpeed(state.speed));
          break;
        case 'BracketRight':
          state.setSpeed(nextSpeed(state.speed));
          break;
        case 'Slash':
          if (event.shiftKey) state.toggleShortcuts();
          break;
        default:
          break;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  /* ------------------------------------------------------------- persist */

  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === 'hidden') persist(true);
    };
    const onUnload = () => persist(true);
    document.addEventListener('visibilitychange', onHide);
    window.addEventListener('beforeunload', onUnload);
    return () => {
      document.removeEventListener('visibilitychange', onHide);
      window.removeEventListener('beforeunload', onUnload);
      persist(true);
    };
  }, [persist]);

  const setVolume = useCallback((value: number) => {
    setVolumeState(value);
    if (audioRef.current) audioRef.current.volume = value;
  }, []);

  return (
    <PlayerContext.Provider value={{ audioRef, volume, setVolume }}>
      <audio
        ref={audioRef}
        preload="auto"
        // Hidden but mounted at the shell level so tab switches never restart audio.
        className="hidden"
        aria-hidden
        data-testid="player-audio"
        data-step={stepIndex}
        data-lesson={bundle?.lesson.key ?? ''}
        data-duration={currentStepDuration(usePlayerStore.getState())}
      />
      {children}
    </PlayerContext.Provider>
  );
}

export function usePlayerEngine(): PlayerEngine {
  const context = useContext(PlayerContext);
  if (!context) {
    return { audioRef: { current: null }, volume: 1, setVolume: () => undefined };
  }
  return context;
}
