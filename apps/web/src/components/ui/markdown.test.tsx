import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Markdown } from '@/components/ui/markdown';

/**
 * T-SEC-4 — generated markdown must not be able to inject script or handlers.
 *
 * The project never uses `dangerouslySetInnerHTML`; this test locks the
 * behaviour in so a future "helpful" refactor cannot regress it. It renders to
 * static markup (the same React tree the browser gets) and inspects the HTML
 * string, which keeps the assertion independent of any act()/test-renderer
 * version skew.
 */
function render(markdown: string): string {
  return renderToStaticMarkup(<Markdown>{markdown}</Markdown>);
}

describe('markdown sanitisation (T-SEC-4)', () => {
  it('escapes raw HTML instead of executing it', () => {
    const html = render(
      '正常文字\n\n<script>window.__pwned = true;</script>\n\n<img src=x onerror="alert(1)">',
    );
    expect(html).toContain('正常文字');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('onerror=');
    // Whether the tag is escaped or dropped, no executable markup survives.
    expect(html).not.toContain('window.__pwned');
  });

  it('drops javascript: links', () => {
    const html = render('[点我](javascript:alert(1))');
    expect(html.toLowerCase()).not.toContain('href="javascript:');
  });

  it('adds a safe rel to external links', () => {
    const html = render('[文档](https://example.com/docs)');
    expect(html).toContain('href="https://example.com/docs"');
    expect(html).toContain('noopener');
  });

  it('still renders GFM tables and inline code', () => {
    const html = render('| 参数 | 含义 |\n| --- | --- |\n| `agent` | Agent 实例 |');
    expect(html).toContain('<table');
    expect(html).toContain('<code');
    expect(html).toContain('agent');
  });
});
