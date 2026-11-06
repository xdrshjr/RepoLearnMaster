'use client';

import { AlertTriangle, ArrowLeft, PanelLeft, Tag } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Badge, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Breadcrumb, FileTree, FontSizeControls, ReadOnlyBadge } from '@/components/ide/file-tree';
import { MonacoEditorPane, type MonacoSelection } from '@/components/ide/monaco-editor-pane';
import { PlainCodeView } from '@/components/ide/plain-code-view';
import { SelectionToolbar } from '@/components/ide/selection-toolbar';
import { useCourseFile } from '@/lib/api/hooks';
import type { CodeNote, EvidenceView, FileRef } from '@/lib/api/types';
import { buildDecorations, splitLines, type AskActionId } from '@/lib/ide/decorations';
import { useCodeFontSize } from '@/lib/ide/font-size';
import { breadcrumbFromPath, useIdeStore } from '@/stores/ide';
import { cn } from '@/lib/utils';

const MONACO_LOAD_TIMEOUT_MS = 4500;

export interface CodePaneProps {
  courseId: string;
  files: FileRef[];
  codeNotes: CodeNote[];
  evidence: EvidenceView[];
  onAsk: (selection: { lineStart: number; lineEnd: number; text: string }, actionId: AskActionId) => void;
  onNoteOpen?: (line: number, text: string) => void;
  className?: string;
}

/**
 * Read-only IDE — spec §7.4.
 *
 * - Monaco (`readOnly` + `domReadOnly`, no line highlight from the editor itself —
 *   all highlighting is decoration-driven);
 * - lazy file fetch per `path` (`GET /api/courses/{id}/files`), cached 1h;
 * - decorations: focus (row tint + 3px accent bar), `code_notes` (line-end icon →
 *   popover), trace evidence (wavy underline);
 * - selection → floating toolbar → streaming answer panel (handled by the page);
 * - a DOM fallback renderer if Monaco cannot load, so the page never goes blank.
 */
export function CodePane({
  courseId,
  files,
  codeNotes,
  evidence,
  onAsk,
  onNoteOpen,
  className,
}: CodePaneProps) {
  const activeFile = useIdeStore((state) => state.activeFile);
  const focus = useIdeStore((state) => state.focus);
  const selection = useIdeStore((state) => state.selection);
  const history = useIdeStore((state) => state.history);
  const openFile = useIdeStore((state) => state.openFile);
  const setSelection = useIdeStore((state) => state.setSelection);
  const openNote = useIdeStore((state) => state.openNote);
  const noteOpenLine = useIdeStore((state) => state.noteOpenLine);
  const goBack = useIdeStore((state) => state.goBack);

  const [fontSize, setFontSize] = useCodeFontSize();
  const [monacoReady, setMonacoReady] = useState(false);
  const [monacoFailed, setMonacoFailed] = useState(false);
  const [treeOpen, setTreeOpen] = useState(false);
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null);
  const paneRef = useRef<HTMLDivElement | null>(null);

  const fileQuery = useCourseFile(courseId, activeFile);

  useEffect(() => {
    setMonacoReady(false);
    setMonacoFailed(false);
    const timer = window.setTimeout(() => {
      setMonacoReady((ready) => {
        if (!ready) {
          setMonacoFailed(true);
          return false;
        }
        return true;
      });
    }, MONACO_LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [courseId]);

  const content = fileQuery.data?.content ?? '';
  const lineCount = useMemo(() => {
    if (fileQuery.data?.line_count) return fileQuery.data.line_count;
    return splitLines(content).length;
  }, [content, fileQuery.data?.line_count]);

  const decorations = useMemo(
    () =>
      buildDecorations({
        file: activeFile ?? '',
        focus,
        codeNotes,
        evidence,
        lineCount,
      }),
    [activeFile, focus, codeNotes, evidence, lineCount],
  );

  const focusLine = focus && focus.file === activeFile ? focus.lineStart : null;

  const handleSelect = useCallback(
    (next: MonacoSelection | null, rect?: DOMRect | null) => {
      if (!next || !activeFile || next.lineStart <= 0) {
        setSelection(null);
        setAnchor(null);
        return;
      }
      setSelection({
        file: activeFile,
        lineStart: next.lineStart,
        lineEnd: next.lineEnd,
        text: next.text.slice(0, 4000),
      });
      if (rect) {
        setAnchor({ top: rect.bottom + 6, left: Math.max(8, rect.left) });
      } else {
        const paneRect = paneRef.current?.getBoundingClientRect();
        setAnchor(paneRect ? { top: paneRect.top + 44, left: paneRect.left + 24 } : null);
      }
    },
    [activeFile, setSelection],
  );

  const handleNoteClick = useCallback(
    (line: number) => {
      const note = codeNotes.find((item) => item.file === activeFile && item.line === line);
      if (!note) return;
      openNote(line);
      onNoteOpen?.(line, note.text);
    },
    [activeFile, codeNotes, onNoteOpen, openNote],
  );

  const breadcrumb = useMemo(() => breadcrumbFromPath(activeFile ?? ''), [activeFile]);

  if (!activeFile) {
    return (
      <div className={cn('grid h-full place-items-center rounded-[var(--radius)] border border-border bg-code-bg p-6 text-center', className)}>
        <div>
          <p className="text-xs text-text-muted">这一层没有需要读的源码文件。</p>
          <p className="mt-1 text-[11px] text-text-dim">切换到“深入源码”可以逐行阅读。</p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={paneRef}
      className={cn(
        'flex h-full min-h-[320px] flex-col overflow-hidden rounded-[var(--radius)] border border-border bg-code-bg',
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-bg-elevated px-2 py-1.5">
        <Button
          variant="ghost"
          size="sm"
          className="px-1.5 md:hidden"
          aria-label="切换文件列表"
          onClick={() => setTreeOpen((open) => !open)}
        >
          <PanelLeft className="size-3.5" aria-hidden />
        </Button>
        <Breadcrumb parts={breadcrumb} />
        <span className="ml-auto flex items-center gap-1.5">
          {history.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={goBack} className="px-1.5" aria-label="返回原位置">
              <ArrowLeft className="size-3.5" aria-hidden />
            </Button>
          ) : null}
          <FontSizeControls value={fontSize} onChange={setFontSize} />
          <ReadOnlyBadge />
        </span>
      </div>

      <div className="flex min-h-0 flex-1">
        <FileTree
          files={files}
          activeFile={activeFile}
          onOpen={(path) => {
            openFile(path);
            setTreeOpen(false);
          }}
          className={cn('w-[190px] shrink-0', treeOpen ? 'block' : 'hidden md:block')}
        />

        <div className="relative min-h-0 min-w-0 flex-1">
          {fileQuery.isLoading ? (
            <div className="space-y-1.5 p-3">
              {Array.from({ length: 12 }).map((_, index) => (
                <Skeleton key={index} className="h-3" />
              ))}
            </div>
          ) : fileQuery.isError ? (
            <div className="p-4">
              <p className="flex items-center gap-1.5 text-xs text-danger">
                <AlertTriangle className="size-3.5" aria-hidden />
                读取文件失败
              </p>
              <p className="mt-1 text-[11px] text-text-muted">
                {fileQuery.error instanceof Error ? fileQuery.error.message : '未知错误'}
              </p>
              <Button variant="outline" size="sm" className="mt-2" onClick={() => void fileQuery.refetch()}>
                重试
              </Button>
            </div>
          ) : monacoFailed ? (
            <PlainCodeView
              content={content}
              decorations={decorations}
              fontSize={fontSize}
              focusLine={focusLine}
              onSelect={(next, rect) =>
                handleSelect(next.lineStart > 0 ? next : null, rect)
              }
              onNoteClick={handleNoteClick}
            />
          ) : (
            // 编辑器必须**立即挂载**：它是否可用只能由自己回报（onReady），
            // 拿这个回报去判断"要不要挂载自己"是自指条件——永远为假，于是
            // 每个代码面板都先转 4.5 秒骨架屏、再永久退化成纯文本视图。
            // 现在的骨架屏只是盖在编辑器之上的一层遮罩，onReady 到达即撤掉。
            <div className="relative h-full" aria-busy={!monacoReady}>
              <MonacoEditorPane
                content={content}
                lang={fileQuery.data?.lang ?? 'text'}
                decorations={decorations}
                fontSize={fontSize}
                focusLine={focusLine}
                onReady={() => setMonacoReady(true)}
                onNoteClick={handleNoteClick}
                onSelect={(next) => handleSelect(next, null)}
              />
              {monacoReady ? null : (
                <div className="absolute inset-0 z-10 space-y-1.5 bg-bg p-3">
                  {Array.from({ length: 10 }).map((_, index) => (
                    <Skeleton key={index} className="h-3" />
                  ))}
                  <p className="pt-2 text-[11px] text-text-dim">正在加载只读编辑器…</p>
                </div>
              )}
            </div>
          )}

          {monacoFailed ? (
            <span className="absolute bottom-2 right-2 rounded border border-warn/40 bg-bg/90 px-2 py-1 text-[10px] text-warn">
              Monaco 不可用，已切换到只读文本视图（高亮与注释仍可用）
            </span>
          ) : null}
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-border px-2 py-1 text-[10px] text-text-dim">
        <span>
          {lineCount} 行
          {fileQuery.data?.truncated ? ' · 已截断' : ''}
        </span>
        <span className="flex items-center gap-1">
          <Tag className="size-2.5" aria-hidden />
          只读教学视图，不会执行仓库代码
        </span>
      </div>

      {selection ? (
        <SelectionToolbar
          selection={selection}
          anchor={anchor}
          onAsk={(actionId) => {
            onAsk(
              { lineStart: selection.lineStart, lineEnd: selection.lineEnd, text: selection.text },
              actionId,
            );
          }}
          onDismiss={() => {
            setSelection(null);
            setAnchor(null);
          }}
        />
      ) : null}

      {noteOpenLine !== null ? (
        <CodeNoteBadge
          notes={codeNotes}
          file={activeFile}
          line={noteOpenLine}
          onClose={() => openNote(null)}
        />
      ) : null}
    </div>
  );
}

function CodeNoteBadge({
  notes,
  file,
  line,
  onClose,
}: {
  notes: CodeNote[];
  file: string;
  line: number;
  onClose: () => void;
}) {
  const note = notes.find((item) => item.file === file && item.line === line);
  if (!note) return null;
  return (
    <div
      role="note"
      className="absolute bottom-10 left-3 right-3 rounded-[var(--radius)] border border-accent/40 bg-surface p-2 text-[11px] text-text shadow-[var(--shadow-soft)]"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="leading-[1.6]">
          <span className="mr-1 font-mono text-accent">L{line}</span>
          {note.text}
        </p>
        <button type="button" onClick={onClose} aria-label="关闭代码注释" className="text-text-dim hover:text-text">
          ✕
        </button>
      </div>
    </div>
  );
}
