'use client';

import { useCallback, useEffect, useState } from 'react';

import { safeLocalStorageGet, safeLocalStorageSet } from '@/lib/utils';

const KEY = 'rl_code_font_size';
const MIN = 12;
const MAX = 16;
const DEFAULT = 13;

/** Code font size is adjustable 12–16 and persisted in localStorage (§7.1). */
export function useCodeFontSize(): [number, (value: number) => void] {
  const [size, setSize] = useState(DEFAULT);

  useEffect(() => {
    const stored = safeLocalStorageGet(KEY);
    const parsed = stored ? Number.parseInt(stored, 10) : Number.NaN;
    if (Number.isFinite(parsed)) setSize(Math.min(MAX, Math.max(MIN, parsed)));
  }, []);

  const update = useCallback((value: number) => {
    const bounded = Math.min(MAX, Math.max(MIN, Math.round(value)));
    setSize(bounded);
    safeLocalStorageSet(KEY, String(bounded));
  }, []);

  return [size, update];
}
