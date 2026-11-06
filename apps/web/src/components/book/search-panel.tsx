'use client';

import { Search } from 'lucide-react';
import { useState } from 'react';

import { Badge, Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { api, isApiError } from '@/lib/api/client';
import type { BookChapterDetail } from '@/lib/api/types';
import { truncate } from '@/lib/format';

export interface SearchHit {
  chapterKey: string;
  chapterTitle: string;
  blockIndex: number;
  snippet: string;
}

/**
 * Full-text search across the book (spec §7.2 P09).
 *
 * The book API exposes chapters one at a time, so "search the whole book" loads
 * every chapter once into a client cache and filters locally — no new endpoint,
 * and re-searching is instant.
 */
export function SearchPanel({
  bookId,
  chapterKeys,
  onJump,
  onCacheUpdate,
}: {
  bookId: string;
  chapterKeys: Array<{ key: string; title: string }>;
  onJump: (chapterKey: string) => void;
  onCacheUpdate?: (chapterKey: string, chapter: BookChapterDetail) => void;
}) {
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    const keyword = query.trim();
    if (!keyword) {
      setHits(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const results: SearchHit[] = [];
      for (const chapter of chapterKeys) {
        const detail = await api.get<BookChapterDetail>(
          `/api/books/${encodeURIComponent(bookId)}/chapters/${encodeURIComponent(chapter.key)}`,
        );
        onCacheUpdate?.(chapter.key, detail);
        detail.blocks.forEach((block, blockIndex) => {
          const text = block.text ?? '';
          const index = text.toLowerCase().indexOf(keyword.toLowerCase());
          if (index === -1) return;
          results.push({
            chapterKey: chapter.key,
            chapterTitle: chapter.title,
            blockIndex,
            snippet: truncate(
              text.slice(Math.max(0, index - 40), Math.min(text.length, index + keyword.length + 60)),
              160,
            ),
          });
        });
      }
      setHits(results);
    } catch (searchError) {
      setError(isApiError(searchError) ? searchError.hint : '搜索失败，请重试。');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="space-y-2">
      <div className="flex items-center gap-1.5">
        <Search className="size-3.5 text-accent" aria-hidden />
        <h3 className="text-xs font-semibold text-text">全文搜索</h3>
        {hits ? <Badge tone="muted">{hits.length} 处命中</Badge> : null}
      </div>
      <div className="flex gap-1.5">
        <TextInput
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void run();
          }}
          placeholder="搜索整本书，例如“工具调用”"
          aria-label="全文搜索"
          className="h-8 text-xs"
        />
        <Button variant="secondary" size="sm" onClick={() => void run()} loading={loading}>
          搜索
        </Button>
      </div>
      {error ? <p className="text-[11px] text-danger">{error}</p> : null}
      {hits ? (
        hits.length === 0 ? (
          <p className="text-[11px] text-text-dim">没有命中。换个关键词试试。</p>
        ) : (
          <ul className="max-h-56 space-y-1 overflow-y-auto rl-scroll-thin">
            {hits.slice(0, 30).map((hit, index) => (
              <li key={`${hit.chapterKey}-${hit.blockIndex}-${index}`}>
                <button
                  type="button"
                  onClick={() => onJump(hit.chapterKey)}
                  className="w-full rounded-[var(--radius-sm)] px-2 py-1.5 text-left hover:bg-surface-2"
                >
                  <span className="block text-[10px] text-text-dim">{hit.chapterTitle}</span>
                  <span className="mt-0.5 block text-[11px] leading-[1.55] text-text-muted">{hit.snippet}</span>
                </button>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </Card>
  );
}
