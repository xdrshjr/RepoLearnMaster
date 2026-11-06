'use client';

import { useRouter } from 'next/navigation';
import { ArrowRight, Github, Loader2, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Badge, Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/client';
import { useCreateCourse } from '@/lib/api/hooks';
import { parseRepoUrl, repoRoute, type ParsedRepo } from '@/lib/repo/parseRepoUrl';
import { cn } from '@/lib/utils';

const EXAMPLES = [
  { label: 'facebook/react', url: 'https://github.com/facebook/react', tag: '大型前端框架' },
  { label: 'microsoft/autogen', url: 'https://github.com/microsoft/autogen', tag: 'Agent 框架' },
  { label: 'fastapi/fastapi', url: 'https://github.com/fastapi/fastapi', tag: 'Python 后端' },
  { label: 'vitejs/vite', url: 'https://github.com/vitejs/vite', tag: '构建工具' },
];

export function HeroImport() {
  const router = useRouter();
  const toast = useToast();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [value, setValue] = useState('');
  const [touched, setTouched] = useState(false);
  const createCourse = useCreateCourse();

  // ⌘K / Ctrl+K focuses the import box: the whole product starts here (§7.2).
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const parsed = useMemo(() => (value.trim() ? parseRepoUrl(value) : null), [value]);
  const inlineError = touched && parsed && !parsed.ok ? parsed.error : null;

  const submit = useCallback(
    (input: string, repo?: ParsedRepo) => {
      const result = repo ? ({ ok: true, repo, warning: null } as const) : parseRepoUrl(input);
      if (!result.ok) {
        setTouched(true);
        return;
      }
      const target = result.repo;
      createCourse.mutate(
        { repoUrl: target.url, ref: target.ref },
        {
          onSuccess: (data) => {
            if (data.reused) {
              toast.push({
                tone: 'info',
                title: '命中已有课程',
                description: '这个 commit 已经生成过课程，直接打开。',
              });
            }
            router.push(repoRoute(target, data.job_id ?? null));
          },
          onError: (error) => {
            if (isApiError(error)) {
              if (error.code === 'SETUP_REQUIRED') {
                router.push('/setup?next=%2F');
                return;
              }
              if (error.code === 'JOB_CONFLICT') {
                const details = error.details as { job_id?: string; course_id?: string } | undefined;
                if (details?.job_id) {
                  router.push(repoRoute(target, details.job_id));
                  return;
                }
              }
              toast.push({
                tone: error.code === 'NETWORK' ? 'warn' : 'error',
                title: `${error.title} · ${error.code}`,
                description: error.hint,
                action: error.retryable
                  ? { label: '重试', onClick: () => submit(target.url, target) }
                  : error.action,
              });
              return;
            }
            toast.push({ tone: 'error', title: '生成失败', description: String(error.message) });
          },
        },
      );
    },
    [createCourse, router, toast],
  );

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    submit(value);
  };

  return (
    <section aria-labelledby="hero-title" className="mx-auto w-full max-w-[820px] px-4 pt-14 text-center">
      <Badge tone="accent" className="mb-5">
        <Sparkles className="size-3" aria-hidden />
        三层 AI 课程 · 每句讲解都能落回 file:line
      </Badge>
      <h1 id="hero-title" className="text-[28px] font-semibold leading-tight tracking-tight text-text sm:text-[36px]">
        把一个 GitHub 仓库
        <br className="hidden sm:block" />
        变成一节可走读的课
      </h1>
      <p className="mx-auto mt-3 max-w-[560px] text-sm leading-[1.65] text-text-muted">
        宏观架构 → 全局走读 → 深入源码。粘贴地址即可生成，课程可复用、可提问、可导出成书。
      </p>

      <form onSubmit={onSubmit} className="mt-7">
        <div
          className={cn(
            'flex items-center gap-2 rounded-[var(--radius-lg)] border bg-surface p-2 transition-colors',
            inlineError ? 'border-danger' : 'border-border focus-within:border-accent',
          )}
        >
          <Github className="ml-2 size-4 shrink-0 text-text-dim" aria-hidden />
          <TextInput
            ref={inputRef}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onBlur={() => setTouched(true)}
            placeholder="https://github.com/owner/repo"
            aria-label="GitHub 仓库地址"
            aria-invalid={Boolean(inlineError)}
            aria-describedby="hero-input-help"
            invalid={Boolean(inlineError)}
            className="h-10 border-0 bg-transparent px-1 focus:border-0"
            autoComplete="off"
            spellCheck={false}
            inputMode="url"
          />
          <Button
            type="submit"
            variant="primary"
            size="md"
            className="shrink-0"
            loading={createCourse.isPending}
            icon={createCourse.isPending ? undefined : <ArrowRight className="size-4" aria-hidden />}
          >
            {createCourse.isPending ? '正在排队…' : '生成学习课程'}
          </Button>
        </div>
        <div id="hero-input-help" className="mt-2 min-h-5 text-left text-xs">
          {inlineError ? (
            <span role="alert" className="text-danger">
              {inlineError}
            </span>
          ) : parsed?.ok ? (
            <span className="text-accent">
              已解析：{parsed.repo.fullName}
              {parsed.repo.ref ? ` @ ${parsed.repo.ref}` : ''}
              {parsed.warning ? ` · ${parsed.warning}` : ''}
            </span>
          ) : (
            <span className="text-text-dim">
              支持粘贴 github.com 链接或直接输入 owner/repo，回车提交 · 按 ⌘K 随时回到这里
            </span>
          )}
        </div>
      </form>

      <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
        <span className="text-[11px] text-text-dim">试试这些：</span>
        {EXAMPLES.map((example) => (
          <button
            key={example.url}
            type="button"
            onClick={() => {
              setValue(example.url);
              setTouched(true);
              inputRef.current?.focus();
            }}
            className="rounded-full border border-border bg-surface px-2.5 py-1 text-[11px] text-text-muted transition-colors hover:border-accent/50 hover:text-text"
          >
            {example.label}
            <span className="ml-1.5 text-text-dim">{example.tag}</span>
          </button>
        ))}
      </div>

      {createCourse.isPending ? (
        <Card className="mx-auto mt-6 flex max-w-[560px] items-center gap-3 text-left">
          <Loader2 className="size-4 animate-spin text-accent" aria-hidden />
          <div>
            <p className="text-xs font-medium text-text">正在解析仓库并排队生成</p>
            <p className="text-[11px] text-text-muted">
              命中缓存的课程会立即返回；否则大约需要 6–12 分钟，可以先去逛逛。
            </p>
          </div>
        </Card>
      ) : null}
    </section>
  );
}
