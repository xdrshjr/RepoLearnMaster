'use client';

import { ArrowUpRight, Copy, Loader2, Send, Square, StopCircle } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { Badge, Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { TextArea } from '@/components/ui/field';
import { Markdown } from '@/components/ui/markdown';
import { useToast } from '@/components/ui/toast';
import { isApiError, openEventStream } from '@/lib/api/client';
import type { EvidenceView } from '@/lib/api/types';
import { toEvidence } from '@/lib/api/types';
import { ASK_ACTIONS, type AskActionId } from '@/lib/ide/decorations';
import { createSseDecoder, toEnvelope } from '@/lib/sse/parse';
import type { LineSelection } from '@/stores/ide';
import { cn } from '@/lib/utils';

export interface AskTurn {
  question: string;
  answer: string;
  evidence: EvidenceView[];
  tokens: number;
}

const QUESTION_BY_ACTION: Record<AskActionId, string> = {
  explain: ASK_ACTIONS[0].question,
  why: ASK_ACTIONS[1].question,
  alternatives: ASK_ACTIONS[2].question,
};

/**
 * Inline ask panel — spec §7.2 行内提问 / §5.2 `POST /courses/{id}/questions`.
 *
 * The answer arrives as SSE (`question.delta` → `question.completed`). We render
 * the accumulated markdown *while streaming* and then replace it with the
 * authoritative `answer_md` from the completion event (T-ASK-1), so the final
 * text never depends on chunk boundaries.
 */
export function InlineAsk({
  courseId,
  selection,
  layer,
  lessonKey,
  initialAction,
  onJumpEvidence,
  onClose,
}: {
  courseId: string;
  selection: LineSelection;
  layer: string;
  lessonKey?: string | null;
  initialAction?: AskActionId | null;
  onJumpEvidence: (evidence: EvidenceView) => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [question, setQuestion] = useState(
    initialAction ? QUESTION_BY_ACTION[initialAction] : '这段代码在做什么？',
  );
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [draft, turns.length]);

  const ask = useCallback(
    async (questionText: string) => {
      const trimmed = questionText.trim();
      if (!trimmed || streaming) return;
      setError(null);
      setStreaming(true);
      setDraft('');
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const response = await openEventStream(
          `/api/courses/${encodeURIComponent(courseId)}/questions`,
          {
            method: 'POST',
            body: {
              file: selection.file,
              line_start: selection.lineStart,
              line_end: selection.lineEnd,
              question: trimmed,
              layer,
              lesson_key: lessonKey ?? undefined,
            },
            signal: controller.signal,
          },
        );

        const body = response.body;
        if (!body) throw new Error('回答流没有响应体。');

        const reader = body.getReader();
        const textDecoder = new TextDecoder();
        const decoder = createSseDecoder();
        let accumulated = '';
        let completed: AskTurn | null = null;

        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = textDecoder.decode(value, { stream: true });
          for (const frame of decoder.push(chunk)) {
            const envelope = toEnvelope(frame);
            if (!envelope) continue;
            if (envelope.type === 'question.delta' || envelope.type === 'agent.text.delta' || envelope.type === 'step.delta') {
              const delta = typeof envelope.data.delta === 'string' ? envelope.data.delta : '';
              accumulated += delta;
              setDraft(accumulated);
            } else if (envelope.type === 'question.completed') {
              const answerMd =
                typeof envelope.data.answerMd === 'string'
                  ? envelope.data.answerMd
                  : typeof envelope.data.answer_md === 'string'
                    ? envelope.data.answer_md
                    : accumulated;
              const evidenceRaw = Array.isArray(envelope.data.evidence) ? envelope.data.evidence : [];
              const tokens = Number(envelope.data.tokens ?? 0);
              completed = {
                question: trimmed,
                answer: answerMd,
                evidence: evidenceRaw
                  .map((item) => toEvidence(item as Record<string, unknown>))
                  .filter((item): item is EvidenceView => Boolean(item)),
                tokens: Number.isFinite(tokens) ? tokens : 0,
              };
            } else if (envelope.type === 'job.failed') {
              const message =
                typeof envelope.data.message === 'string' ? envelope.data.message : '生成回答失败。';
              setError(message);
            }
          }
          if (completed) break;
        }

        const finalTurn =
          completed ??
          ({
            question: trimmed,
            answer: accumulated,
            evidence: [],
            tokens: 0,
          } satisfies AskTurn);
        setTurns((current) => [...current, finalTurn]);
        setDraft('');
      } catch (streamError) {
        if (streamError instanceof DOMException && streamError.name === 'AbortError') {
          if (draft) {
            setTurns((current) => [
              ...current,
              { question: trimmed, answer: draft, evidence: [], tokens: 0 },
            ]);
          }
        } else if (isApiError(streamError)) {
          setError(`${streamError.title}：${streamError.hint}`);
        } else {
          setError(streamError instanceof Error ? streamError.message : '提问失败。');
        }
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [courseId, draft, layer, lessonKey, selection, streaming],
  );

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-xs font-semibold text-text">对选中代码提问</h3>
        <Badge tone="info">layer {layer}</Badge>
        <span className="font-mono text-[10px] text-text-dim">
          {selection.file}:{selection.lineStart}
          {selection.lineEnd > selection.lineStart ? `-${selection.lineEnd}` : ''}
        </span>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={onClose}>
          收起
        </Button>
      </div>

      <pre className="max-h-24 overflow-auto rounded-[var(--radius-sm)] border border-border bg-code-bg p-2 font-mono text-[10px] leading-[1.5] text-text-muted">
        {selection.text.slice(0, 800) || '（未捕获到选中文本，回答将基于行号推断）'}
      </pre>

      <div className="flex flex-wrap gap-1">
        {ASK_ACTIONS.map((action) => (
          <Button
            key={action.id}
            variant="outline"
            size="sm"
            onClick={() => {
              setQuestion(action.question);
              void ask(action.question);
            }}
            disabled={streaming}
          >
            {action.label}
          </Button>
        ))}
      </div>

      <div className="max-h-72 space-y-3 overflow-y-auto rounded-[var(--radius-sm)] border border-border bg-surface-2/30 p-2.5 rl-scroll-thin" ref={scrollRef}>
        {turns.length === 0 && !draft && !streaming ? (
          <p className="text-[11px] text-text-dim">
            答案会带证据列表（文件:行），点一下就能跳回源码核对。
          </p>
        ) : null}

        {turns.map((turn, index) => (
          <div key={index} className="space-y-1.5">
            <p className="text-[11px] font-medium text-accent">Q：{turn.question}</p>
            <Markdown compact>{turn.answer}</Markdown>
            {turn.evidence.length > 0 ? (
              <ul className="space-y-0.5 border-t border-border pt-1.5">
                {turn.evidence.map((item, itemIndex) => (
                  <li key={`${item.file}-${item.line_start}-${itemIndex}`}>
                    <button
                      type="button"
                      onClick={() => onJumpEvidence(item)}
                      className="inline-flex items-center gap-0.5 font-mono text-[10px] text-info underline decoration-dotted underline-offset-2 hover:text-accent"
                    >
                      {item.file}:{item.line_start}
                      <ArrowUpRight className="size-2.5" aria-hidden />
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            {turn.tokens ? (
              <p className="text-[10px] text-text-dim">{turn.tokens} tokens</p>
            ) : null}
          </div>
        ))}

        {streaming ? (
          <div className="space-y-1.5">
            <p className="flex items-center gap-1 text-[11px] font-medium text-accent">
              <Loader2 className="size-3 animate-spin" aria-hidden />
              正在回答
            </p>
            {draft ? <Markdown compact>{draft}</Markdown> : null}
            <span aria-hidden className="inline-block h-3 w-1.5 animate-pulse bg-accent align-middle" />
          </div>
        ) : null}

        <div aria-live="polite">
          {error ? (
            <div className="rounded-[var(--radius-sm)] border border-danger/40 bg-danger/10 px-2 py-1.5">
              <p className="text-[11px] text-danger">{error}</p>
              <Button
                variant="ghost"
                size="sm"
                className="mt-1"
                onClick={() => void ask(question)}
              >
                重试
              </Button>
            </div>
          ) : null}
        </div>
      </div>

      <div className="space-y-1.5">
        <TextArea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="继续追问：例如“如果把这里改成异步会怎样？”"
          aria-label="提问内容"
          className="min-h-16 text-xs"
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              void ask(question);
            }
          }}
        />
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={() => void ask(question)}
            loading={streaming}
            disabled={!question.trim()}
            icon={<Send className="size-3" aria-hidden />}
          >
            提问
          </Button>
          {streaming ? (
            <Button
              variant="danger"
              size="sm"
              onClick={() => abortRef.current?.abort()}
              icon={<Square className="size-3" aria-hidden />}
            >
              停止
            </Button>
          ) : null}
          {turns.length > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                void navigator.clipboard?.writeText(turns.map((turn) => turn.answer).join('\n\n'));
                toast.push({ tone: 'success', title: '已复制回答' });
              }}
              icon={<Copy className="size-3" aria-hidden />}
            >
              复制回答
            </Button>
          ) : null}
          <span className={cn('ml-auto text-[10px] text-text-dim')}>
            ⌘/Ctrl + Enter 发送
            {turns.some((turn) => turn.tokens) ? (
              <span className="ml-1 inline-flex items-center gap-0.5">
                <StopCircle className="size-2.5" aria-hidden />
                计费按回答实际 tokens
              </span>
            ) : null}
          </span>
        </div>
      </div>
    </Card>
  );
}
