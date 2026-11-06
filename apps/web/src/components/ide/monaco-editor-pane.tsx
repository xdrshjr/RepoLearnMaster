'use client';

/* eslint-disable @typescript-eslint/no-explicit-any */

import dynamic from 'next/dynamic';
import { useEffect, useRef } from 'react';

import { Skeleton } from '@/components/ui/card';
import type { LineDecoration } from '@/lib/ide/decorations';

/**
 * Monaco is loaded lazily and only on the client (`ssr: false`). The package
 * ships the *wrapper*; the editor itself is fetched by the AMD loader, so an
 * offline dev box will never resolve it — `CodePane` therefore races a timer
 * and falls back to a plain (still decorated) code view instead of showing a
 *永久 spinner.
 */
const MonacoEditor = dynamic(() => import('@monaco-editor/react').then((mod) => mod.default), {
  ssr: false,
  loading: () => (
    <div className="space-y-1 p-3">
      <Skeleton className="h-3 w-2/3" />
      <Skeleton className="h-3 w-5/6" />
      <Skeleton className="h-3 w-1/2" />
    </div>
  ),
});

export interface MonacoSelection {
  lineStart: number;
  lineEnd: number;
  text: string;
}

/**
 * 选区在**视口坐标**下的矩形（与 `DOMRect` 结构兼容，因此 `PlainCodeView`
 * 里 `range.getBoundingClientRect()` 的结果可以直接传过来）。
 */
export interface SelectionRect {
  top: number;
  left: number;
  bottom: number;
  right: number;
  width: number;
  height: number;
}

export interface MonacoPaneProps {
  content: string;
  lang: string;
  decorations: LineDecoration[];
  fontSize: number;
  focusLine: number | null;
  /** `rect` 是选区在视口里的真实位置；算不出来时回传 `null`（上层用兜底偏移）。 */
  onSelect: (selection: MonacoSelection | null, rect: SelectionRect | null) => void;
  onNoteClick: (line: number) => void;
  onReady: () => void;
}

/**
 * 把 Monaco 的"滚动后可见位置"换算成视口坐标（评审 P1-6 / 实证 E11）。
 *
 * 旧实现只回传行号，于是工具条锚点只能猜（面板左上角 + 固定偏移），在桌面上
 * 也永远贴着面板左上角——用户会以为工具条坏了。这里用
 * `editor.getScrolledVisiblePosition()`（相对编辑区左上角）+ 编辑区
 * `getBoundingClientRect()`（相对视口）相加，得到与 `position: fixed` 一致的
 * 坐标系；任何一步拿不到（选区已被滚出可见区、编辑器还没布局完）就返回 `null`，
 * 让上层退化而不是让页面崩。
 */
function toViewportRect(editor: any, selection: any): SelectionRect | null {
  try {
    const domNode = editor.getDomNode?.() as HTMLElement | null;
    const domRect = domNode?.getBoundingClientRect?.();
    if (!domRect) return null;

    const start = editor.getScrolledVisiblePosition?.({
      lineNumber: selection.startLineNumber,
      column: selection.startColumn,
    });
    if (!start || typeof start.top !== 'number' || typeof start.left !== 'number') return null;

    const lineHeight = typeof start.height === 'number' && start.height > 0 ? start.height : 18;
    const lineSpan = Math.max(1, selection.endLineNumber - selection.startLineNumber + 1);
    const end = editor.getScrolledVisiblePosition?.({
      lineNumber: selection.endLineNumber,
      column: selection.endColumn,
    });

    const top = domRect.top + start.top;
    const left = domRect.left + start.left;
    const bottom =
      end && typeof end.top === 'number' ? domRect.top + end.top + lineHeight : top + lineHeight * lineSpan;
    const right = end && typeof end.left === 'number' ? domRect.left + end.left : left;

    return {
      top,
      left,
      bottom: Math.max(bottom, top + 1),
      right: Math.max(right, left),
      width: Math.max(0, right - left),
      height: Math.max(1, bottom - top),
    };
  } catch {
    // 第三方编辑器在卸载/重建期间会抛（`getModel()` 已销毁等），这里不兜底就会
    // 让整个代码面板白屏——工具条少一次精确定位远好过硬崩。
    return null;
  }
}

function toMonacoDecorations(monaco: any, decorations: LineDecoration[]) {
  return decorations.map((decoration) => {
    const range = new monaco.Range(
      decoration.lineStart,
      1,
      decoration.lineEnd,
      1,
    );
    if (decoration.kind === 'focus') {
      return {
        range,
        options: {
          isWholeLine: true,
          className: 'rl-deco-focus',
          linesDecorationsClassName: 'rl-deco-focus-bar',
        },
      };
    }
    if (decoration.kind === 'note') {
      return {
        range,
        options: {
          isWholeLine: true,
          glyphMarginClassName: 'rl-deco-note-glyph',
          glyphMarginHoverMessage: { value: decoration.note ?? '' },
          linesDecorationsClassName: 'rl-deco-note-mark',
        },
      };
    }
    return {
      range,
      options: {
        isWholeLine: true,
        inlineClassName: 'rl-deco-evidence',
      },
    };
  });
}

export function MonacoEditorPane({
  content,
  lang,
  decorations,
  fontSize,
  focusLine,
  onSelect,
  onNoteClick,
  onReady,
}: MonacoPaneProps) {
  const editorRef = useRef<any>(null);
  const monacoRef = useRef<any>(null);
  const decorationIds = useRef<string[]>([]);

  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editor || !monaco) return;
    decorationIds.current = editor.deltaDecorations(
      decorationIds.current,
      toMonacoDecorations(monaco, decorations),
    );
  }, [decorations, content]);

  useEffect(() => {
    if (focusLine == null) return;
    const editor = editorRef.current;
    if (!editor) return;
    editor.revealLineInCenter(focusLine);
    editor.setPosition({ lineNumber: focusLine, column: 1 });
  }, [focusLine]);

  return (
    <MonacoEditor
      height="100%"
      language={lang === 'text' ? 'plaintext' : lang}
      value={content}
      theme="repolearn"
      beforeMount={(monaco: any) => {
        monaco.editor.defineTheme('repolearn', {
          base: 'vs-dark',
          inherit: true,
          rules: [
            { token: 'comment', foreground: '6D837C', fontStyle: 'italic' },
            { token: 'string', foreground: '9FE6C4' },
            { token: 'keyword', foreground: '3ECF8E' },
            { token: 'number', foreground: 'E8B44A' },
            { token: 'type', foreground: '6CA8F5' },
          ],
          colors: {
            'editor.background': '#0F1513',
            'editor.foreground': '#E6EDEA',
            'editorLineNumber.foreground': '#3A4642',
            'editorLineNumber.activeForeground': '#9FB0AA',
            'editor.selectionBackground': '#2A4038',
            'editor.lineHighlightBorder': '#00000000',
            'editorGutter.background': '#0F1513',
            'editorCursor.foreground': '#3ECF8E',
          },
        });
      }}
      onMount={(editor: any, monaco: any) => {
        editorRef.current = editor;
        monacoRef.current = monaco;
        decorationIds.current = editor.deltaDecorations(
          [],
          toMonacoDecorations(monaco, decorations),
        );
        onReady();

        editor.onDidChangeCursorSelection(() => {
          const model = editor.getModel();
          const selection = editor.getSelection();
          if (!model || !selection) {
            onSelect(null, null);
            return;
          }
          const text = model.getValueInRange(selection);
          if (!text || text.trim().length === 0) {
            onSelect(null, null);
            return;
          }
          onSelect(
            {
              lineStart: selection.startLineNumber,
              lineEnd: selection.endLineNumber,
              text,
            },
            // 真实选区 rect（视口坐标）——工具条"跟着选区走"的唯一来源
            toViewportRect(editor, selection),
          );
        });

        editor.onMouseDown((event: any) => {
          const line = event?.target?.position?.lineNumber;
          if (typeof line === 'number') onNoteClick(line);
        });
      }}
      options={{
        readOnly: true,
        domReadOnly: true,
        renderLineHighlight: 'none',
        minimap: { enabled: typeof window !== 'undefined' && window.innerWidth > 1100 },
        fontFamily: 'JetBrains Mono, Cascadia Mono, Consolas, monospace',
        fontSize,
        lineHeight: Math.round(fontSize * 1.55),
        scrollBeyondLastLine: false,
        glyphMargin: true,
        folding: true,
        wordWrap: 'off',
        contextmenu: false,
        smoothScrolling: true,
        automaticLayout: true,
        padding: { top: 8, bottom: 8 },
        scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
      }}
    />
  );
}
