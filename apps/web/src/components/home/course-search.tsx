'use client';

/**
 * 首页搜索框（spec §4.3 #49 / §3.4.4）——离线层可测，零后端。
 *
 * 四个行为都是"用户能感觉到"的，因此每一条都有对应的断言：
 *  1. 输入 → 300ms 防抖 → `GET /api/courses?q=…`；列表**不闪空态**
 *     （`placeholderData: keepPreviousData`，见 `hooks.ts`）；
 *  2. 输入框下方小字显示**实际生效的模式**（`fts` / `scan`）与回退原因——
 *     否则"搜不到"永远没人说得清是索引没生效还是真的没有；
 *  3. `/` 快捷键聚焦（在输入框里按 `/` 仍然是打字符，不抢焦点）；
 *  4. 高亮一律由 React 元素渲染 `<mark>`，服务端只给 `{text, marked}` 切段，
 *     因此这里（以及全仓）不需要 `dangerouslySetInnerHTML`。
 *
 * 无障碍：input 有 `aria-label`，结果区由 `SearchResults` 的 `role="status"`
 * 播报"找到 N 门课"，本组件再为"正在搜索…"提供一个只读的 live region
 * （两件事不同，合成一个会变成重复播报）。
 */

import { Search, X } from 'lucide-react';
import { useCallback, useDeferredValue, useEffect, useRef, useState } from 'react';

import { TextInput } from '@/components/ui/field';
import { SearchResults } from '@/components/home/course-sections';
import { useCourseSearch } from '@/lib/api/hooks';

/** 与后端 fts 的 trigram 门槛同一个数字（`MIN_TRIGRAM = 3`）。 */
const MIN_TRIGRAM = 3;
/** 防抖窗口：既压住每键一次请求，又小于"人觉得卡"的阈值。 */
const DEBOUNCE_MS = 300;

/**
 * 300ms 防抖。`useDeferredValue` 单独用**不**是防抖（它只降低更新优先级，
 * 打字快的时候仍然每个值都发一次请求），所以两个机制各司其职：
 * 定时器决定"何时查"，deferred value 决定"渲染不阻塞输入"。
 */
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

export interface ModeHint {
  text: string;
  tone: 'accent' | 'warn' | 'dim';
}

/**
 * 模式提示的**文案表**（spec §3.4.4 + 硬化的 T-SEARCH-8）。
 *
 * 顺序即语义：先看回退原因（它才是用户实际经历的路径），再看生效模式。
 * `fallback_reason` 比 `mode` 更具体，所以它优先——`mode=scan` 既有"配置就是
 * scan"也有"配置 fts 但查询太短"，把两者说成同一句话等于把 G3 的谎言换个地方说。
 */
export function modeHint(
  mode: string | undefined,
  fallbackReason: string | null | undefined,
): ModeHint {
  if (fallbackReason === 'query_too_short') {
    return { text: '按创建时间列出（查询短于 3 字，索引不适用）', tone: 'warn' };
  }
  if (fallbackReason === 'sqlite_too_old') {
    return { text: '当前运行时不支持全文索引，已按 LIKE 搜索', tone: 'warn' };
  }
  // `index_missing` / `probe_failed` 是服务端"查了库才发现没有索引表"的结论。
  // 落到下面的 `mode === 'scan'` 分支会写成"未启用全文索引"，把一句**可执行的**
  // 结论（跑 `reindex-search` 就能修）藏成了一句配置说明。
  if (fallbackReason === 'index_missing' || fallbackReason === 'probe_failed') {
    return { text: '索引表缺失，已按 LIKE 搜索（可运行 reindex-search 重建）', tone: 'warn' };
  }
  if (mode === 'fts') return { text: '全文索引（≥3 字）', tone: 'accent' };
  if (mode === 'scan') return { text: '按创建时间列出（未启用全文索引）', tone: 'dim' };
  return { text: `输入关键词开始搜索（≥${MIN_TRIGRAM} 字使用全文索引）`, tone: 'dim' };
}

const HINT_TONE: Record<ModeHint['tone'], string> = {
  accent: 'text-accent',
  warn: 'text-warn',
  dim: 'text-text-dim',
};

export function CourseSearch() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [value, setValue] = useState('');
  const debounced = useDebouncedValue(value, DEBOUNCE_MS);
  const query = useDeferredValue(debounced.trim());

  const search = useCourseSearch(query);
  const hint = modeHint(search.data?.mode, search.data?.fallback_reason);

  // `/` 聚焦。刻意不处理"焦点已经在输入框里"的情况：那时 `/` 是字符，不是快捷键。
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable) {
          return;
        }
      }
      event.preventDefault();
      inputRef.current?.focus();
      inputRef.current?.select();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const clear = useCallback(() => {
    setValue('');
    inputRef.current?.focus();
  }, []);

  const onKeyDownInput = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape' && value.length > 0) {
      event.preventDefault();
      clear();
    }
  };

  return (
    <section aria-labelledby="home-search-title" className="mx-auto mt-10 w-full max-w-[820px] px-4">
      <h2 id="home-search-title" className="sr-only">
        搜索课程
      </h2>

      <div className="flex items-center gap-2 rounded-[var(--radius-lg)] border border-border bg-surface p-2 focus-within:border-accent">
        <Search className="ml-2 size-4 shrink-0 text-text-dim" aria-hidden />
        <TextInput
          ref={inputRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDownInput}
          placeholder="搜索课程 / 仓库（如 缓存、react）"
          aria-label="搜索课程"
          aria-describedby="home-search-mode"
          className="h-9 border-0 bg-transparent px-1 focus:border-0"
          autoComplete="off"
          spellCheck={false}
        />
        {value.length > 0 ? (
          <button
            type="button"
            onClick={clear}
            aria-label="清空搜索关键词"
            className="shrink-0 rounded-[var(--radius-sm)] p-1.5 text-text-dim transition-colors hover:bg-surface-2 hover:text-text"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        ) : (
          <kbd
            aria-hidden
            className="mr-1 hidden shrink-0 rounded-[var(--radius-sm)] border border-border px-1.5 py-0.5 text-[10px] text-text-dim sm:block"
          >
            /
          </kbd>
        )}
      </div>

      <p id="home-search-mode" className={`mt-1.5 min-h-4 text-[11px] ${HINT_TONE[hint.tone]}`}>
        {hint.text}
      </p>

      {/* 只播报"正在查"，结果条数由 SearchResults 的 role="status" 播报（两者不同）。 */}
      <p aria-live="polite" className="sr-only">
        {query.length > 0 && search.isFetching ? '正在搜索…' : ''}
      </p>

      {query.length > 0 ? (
        <SearchResults
          query={query}
          data={search.data}
          isLoading={search.isLoading || search.isFetching}
          isPlaceholderData={search.isPlaceholderData}
          isError={search.isError}
          errorMessage={search.error instanceof Error ? search.error.message : null}
          onRetry={() => void search.refetch()}
        />
      ) : null}
    </section>
  );
}
