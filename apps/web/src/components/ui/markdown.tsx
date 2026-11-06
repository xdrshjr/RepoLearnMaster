'use client';

/**
 * Sanitised markdown renderer — the ONLY way generated text reaches the DOM.
 *
 * `dangerouslySetInnerHTML` is banned in this codebase (spec §2.2 / §7.6).
 */

import { memo } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';

import { markdownSanitizeSchema, SAFE_LINK_REL } from '@/lib/markdown/sanitize';
import { cn } from '@/lib/utils';

export interface MarkdownProps {
  children: string;
  className?: string;
  /** Tighter spacing for inline answers inside a rail. */
  compact?: boolean;
}

export const Markdown = memo(function Markdown({ children, className, compact = false }: MarkdownProps) {
  return (
    <div
      className={cn(
        'text-text text-sm leading-[1.65]',
        compact ? 'space-y-1.5' : 'space-y-3',
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeSanitize, markdownSanitizeSchema]]}
        components={{
          p: ({ children: content }) => <p className="leading-[1.65]">{content}</p>,
          a: ({ children: content, href }) => (
            <a
              href={href}
              target="_blank"
              rel={SAFE_LINK_REL}
              className="text-accent underline decoration-accent/40 underline-offset-2 hover:text-accent-strong"
            >
              {content}
            </a>
          ),
          h1: ({ children: content }) => <h3 className="text-lg font-semibold">{content}</h3>,
          h2: ({ children: content }) => <h4 className="text-base font-semibold">{content}</h4>,
          h3: ({ children: content }) => <h5 className="text-sm font-semibold">{content}</h5>,
          h4: ({ children: content }) => <h6 className="text-sm font-semibold">{content}</h6>,
          ul: ({ children: content }) => (
            <ul className="list-disc space-y-1 pl-5 marker:text-text-dim">{content}</ul>
          ),
          ol: ({ children: content }) => (
            <ol className="list-decimal space-y-1 pl-5 marker:text-text-dim">{content}</ol>
          ),
          blockquote: ({ children: content }) => (
            <blockquote className="border-l-2 border-border-strong pl-3 text-text-muted">
              {content}
            </blockquote>
          ),
          code: ({ children: content, className: codeClassName }) => {
            const isBlock = typeof codeClassName === 'string' && codeClassName.includes('language-');
            if (isBlock) {
              return <code className={cn('font-mono text-xs', codeClassName)}>{content}</code>;
            }
            return (
              <code className="rounded bg-code-bg px-1.5 py-0.5 font-mono text-[0.92em] text-accent">
                {content}
              </code>
            );
          },
          pre: ({ children: content }) => (
            <pre className="overflow-x-auto rounded-[var(--radius-sm)] border border-border bg-code-bg p-3 font-mono text-xs leading-[1.55]">
              {content}
            </pre>
          ),
          table: ({ children: content }) => (
            <div className="overflow-x-auto rounded-[var(--radius-sm)] border border-border">
              <table className="w-full border-collapse text-xs">{content}</table>
            </div>
          ),
          th: ({ children: content }) => (
            <th className="border-b border-border bg-surface-2 px-2 py-1.5 text-left font-medium text-text-muted">
              {content}
            </th>
          ),
          td: ({ children: content }) => (
            <td className="border-b border-border/60 px-2 py-1.5 align-top">{content}</td>
          ),
          hr: () => <hr className="border-border" />,
          img: ({ src, alt }) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={typeof src === 'string' ? src : ''}
              alt={alt ?? ''}
              className="max-w-full rounded-[var(--radius-sm)] border border-border"
              loading="lazy"
            />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
});
