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

export interface MonacoPaneProps {
  content: string;
  lang: string;
  decorations: LineDecoration[];
  fontSize: number;
  focusLine: number | null;
  onSelect: (selection: MonacoSelection | null) => void;
  onNoteClick: (line: number) => void;
  onReady: () => void;
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
            onSelect(null);
            return;
          }
          const text = model.getValueInRange(selection);
          if (!text || text.trim().length === 0) {
            onSelect(null);
            return;
          }
          onSelect({
            lineStart: selection.startLineNumber,
            lineEnd: selection.endLineNumber,
            text,
          });
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
