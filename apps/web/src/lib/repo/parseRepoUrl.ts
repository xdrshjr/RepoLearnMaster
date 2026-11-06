/**
 * Instant client-side GitHub URL parsing for the home page hero input
 * (spec §7.2: “输入框粘贴即解析、非法 URL 即时内联报错”).
 *
 * No network call: validation is a pure function so the inline error appears on
 * the keystroke, and the same parser is reused by the deep-link pages.
 */

export interface ParsedRepo {
  owner: string;
  name: string;
  /** `owner/name`, the canonical cache key. */
  fullName: string;
  /** Canonical https URL. */
  url: string;
  /** Optional ref pulled out of `/tree/<ref>` links; `null` when absent. */
  ref: string | null;
}

export type RepoParseResult =
  | { ok: true; repo: ParsedRepo; warning: string | null }
  | { ok: false; error: string };

const OWNER_RE = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/;
const NAME_RE = /^[A-Za-z0-9._-]{1,100}$/;
const RESERVED_OWNERS = new Set(['orgs', 'settings', 'features', 'about', 'pricing', 'topics', 'search', 'explore', 'login', 'marketplace']);

/**
 * 百分号解码必须容错：`github.com/o/r/tree/100%` 是用户可能真的会粘贴的东西，
 * 而 `decodeURIComponent` 遇到孤立 `%` 会抛 `URIError`。这个函数在
 * `useMemo` 里、渲染期间执行，抛错等于把整页打成白屏——一个非法字符不该有
 * 这么大的破坏力，退回原文即可。
 */
function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export function parseRepoUrl(input: string): RepoParseResult {
  const raw = input.trim();
  if (!raw) return { ok: false, error: '粘贴一个 GitHub 仓库地址，例如 https://github.com/facebook/react' };
  if (raw.length > 400) return { ok: false, error: '地址过长（上限 400 字符）' };
  if (/\s/.test(raw)) return { ok: false, error: '地址里不能有空格，请只粘贴仓库链接' };

  let path = raw;
  let protocol = 'https://';

  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(raw)) {
    let url: URL;
    try {
      url = new URL(raw);
    } catch {
      return { ok: false, error: '这不像一个合法链接' };
    }
    if (!/(^|\.)github\.com$/i.test(url.hostname)) {
      return { ok: false, error: '目前只支持 github.com 的公开仓库' };
    }
    protocol = `${url.protocol}//`;
    path = `${url.hostname}${url.pathname}`;
  } else if (/^github\.com\//i.test(raw)) {
    path = raw;
  } else if (/^git@github\.com:/i.test(raw)) {
    path = raw.replace(/^git@github\.com:/i, 'github.com/');
  }

  // Strip a trailing `.git`, query string, hash and any `/tree/<ref>/...` tail.
  path = path.split('#')[0]!.split('?')[0]!;
  const segments = path
    .replace(/^github\.com\//i, '')
    .replace(/\.git$/i, '')
    .split('/')
    .filter((segment) => segment.length > 0);

  if (segments.length < 2) {
    return { ok: false, error: '需要形如 owner/repo 的两段路径' };
  }

  const [owner, name, ...rest] = segments as [string, string, ...string[]];
  if (RESERVED_OWNERS.has(owner.toLowerCase())) {
    return { ok: false, error: `“${owner}” 不是仓库名，请粘贴具体仓库链接` };
  }
  if (!OWNER_RE.test(owner)) return { ok: false, error: `owner “${owner}” 只能包含字母、数字和连字符` };
  if (!NAME_RE.test(name)) return { ok: false, error: `仓库名 “${name}” 含非法字符` };

  let ref: string | null = null;
  let warning: string | null = null;
  if (rest.length >= 2 && (rest[0] === 'tree' || rest[0] === 'blob')) {
    ref = rest.slice(1).join('/') || null;
    warning = ref ? `已解析出分支/标签：${safeDecode(ref)}` : null;
  } else if (rest.length > 0) {
    warning = '已只保留 owner/repo 部分，子路径会在生成时由课程自动定位';
  }

  const cleanName = name.replace(/\.git$/i, '');
  return {
    ok: true,
    repo: {
      owner,
      name: cleanName,
      fullName: `${owner}/${cleanName}`,
      url: `${protocol}github.com/${owner}/${cleanName}`,
      ref,
    },
    warning,
  };
}

/** Route helper used by the home page submit and by deep links. */
export function repoRoute(repo: { owner: string; name: string }, jobId?: string | null): string {
  const base = `/repo/${encodeURIComponent(repo.owner)}/${encodeURIComponent(repo.name)}`;
  return jobId ? `${base}?job=${encodeURIComponent(jobId)}` : base;
}

export function courseRoute(courseId: string, layer: 'overview' | 'walkthrough' | 'deep-dive' | 'recap' = 'overview'): string {
  return `/course/${encodeURIComponent(courseId)}/${layer}`;
}
