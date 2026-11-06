'use client';

/**
 * Read-only IDE store — spec §7.4.
 *
 * Keeps the open file, the focused line range and the selection prompt state
 * out of the component tree so that jumping from an architecture node → code →
 * back to the original position (T-IDE-1) survives tab switches.
 */

import { create } from 'zustand';

import type { FileRef } from '@/lib/api/types';

export interface FocusTarget {
  file: string;
  lineStart: number;
  lineEnd: number;
}

export interface LineSelection extends FocusTarget {
  text: string;
}

interface IdeStore {
  courseId: string | null;
  files: FileRef[];
  activeFile: string | null;
  focus: FocusTarget | null;
  selection: LineSelection | null;
  /** Line whose code note popover is open (null = closed). */
  noteOpenLine: number | null;
  /** Breadcrumb symbol stack, e.g. ['pkg', 'module.py', 'Class', 'func']. */
  breadcrumb: string[];
  askOpen: boolean;
  history: FocusTarget[];

  setCourse: (courseId: string, files: FileRef[]) => void;
  openFile: (file: string, focus?: FocusTarget | null, options?: { remember?: boolean }) => void;
  setFocus: (focus: FocusTarget | null) => void;
  setSelection: (selection: LineSelection | null) => void;
  openNote: (line: number | null) => void;
  setBreadcrumb: (parts: string[]) => void;
  setAskOpen: (open: boolean) => void;
  /** Restore the previous focus target (the "返回原位置" affordance). */
  goBack: () => void;
  canGoBack: () => boolean;
  reset: () => void;
}

const initial = {
  courseId: null as string | null,
  files: [] as FileRef[],
  activeFile: null as string | null,
  focus: null as FocusTarget | null,
  selection: null as LineSelection | null,
  noteOpenLine: null as number | null,
  breadcrumb: [] as string[],
  askOpen: false,
  history: [] as FocusTarget[],
};

export const useIdeStore = create<IdeStore>((set, get) => ({
  ...initial,

  setCourse: (courseId, files) =>
    set((state) => ({
      courseId,
      files,
      activeFile: state.activeFile && files.some((f) => f.path === state.activeFile)
        ? state.activeFile
        : (files[0]?.path ?? state.activeFile),
    })),

  openFile: (file, focus, options) =>
    set((state) => {
      const previous =
        options?.remember !== false && state.focus && state.focus.file !== file
          ? [...state.history, state.focus].slice(-20)
          : state.history;
      const next: Partial<IdeStore> = { activeFile: file };
      if (focus) next.focus = focus;
      else if (state.focus && state.focus.file !== file) next.focus = null;
      if (options?.remember !== false) next.history = previous;
      return next;
    }),

  setFocus: (focus) => set({ focus }),

  setSelection: (selection) => set({ selection, askOpen: selection !== null }),

  openNote: (line) => set({ noteOpenLine: line }),

  setBreadcrumb: (parts) => set({ breadcrumb: parts }),

  setAskOpen: (open) => set({ askOpen: open }),

  goBack: () =>
    set((state) => {
      const history = [...state.history];
      const previous = history.pop();
      if (!previous) return { history, focus: null };
      return { history, activeFile: previous.file, focus: previous };
    }),

  canGoBack: () => get().history.length > 0,

  reset: () => set({ ...initial }),
}));

/** `pkg/module.py > Class > func` breadcrumb derived from a file path + symbol. */
export function breadcrumbFromPath(path: string, symbol?: string | null): string[] {
  const parts = path.split('/');
  if (parts.length === 0) return symbol ? [symbol] : [];
  const file = parts[parts.length - 1] ?? path;
  const dirs = parts.slice(0, -1);
  const head = dirs.length > 0 ? dirs.join('/') : '';
  const chain = head ? [head, file] : [file];
  if (symbol) chain.push(symbol);
  return chain;
}
