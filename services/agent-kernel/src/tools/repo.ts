/**
 * 只读仓库工具（spec §3.5.2 / §4.2）。
 *
 * 安全模型（这条比功能更重要）：`mirrorDir` 是不可信输入的沙箱根。每个路径参数
 * 都必须 `path.resolve(root, p)` 之后 **startsWith(root)**，否则 `../../secret`
 * 就变成"Kernel 替我读宿主机文件"。
 *
 * 为什么用 `defineTool` 而不是自己手搓一个 tool 对象：`defineTool` 是 core 的
 * 官方扩展点，它的 `parameters` 会被 ToolParamValidator 校验、执行结果会被
 * ToolExecutor 纳入超时/取消语义。绕过它等于把重试与取消一起绕过去。
 */

import fs from 'node:fs/promises';
import { readdir, readFile, stat } from 'node:fs/promises';
import path from 'node:path';

import { defineTool } from '@aragon-agent/core';

import { fail, ok } from './result.ts';

export const MAX_FILE_BYTES = 256 * 1024;
export const MAX_GREP_MATCHES = 200;
export const MAX_TREE_ENTRIES = 400;

/** 拒绝的路径形状（Windows 设备名比 POSIX 多一类坑，spec §3.12 / T-SEC-2）。 */
const WINDOWS_DEVICE = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$/i;

export interface GuardResult {
  ok: boolean;
  reason?: string;
  abs?: string;
}

/**
 * 把用户/模型给的相对路径解析为沙箱内的绝对路径。
 *
 * 返回 discriminated result 而不是抛错，是因为工具层要能**把错误当作给模型的
 * 反馈**（"路径越界"这条信息对模型有用），而不是让整条 run 崩掉。
 */
export function resolveInside(root: string, rel: string): GuardResult {
  if (typeof rel !== 'string' || rel.trim() === '') return { ok: false, reason: 'empty path' };
  const raw = rel.replace(/\\/g, '/');
  if (raw.includes('\0')) return { ok: false, reason: 'null byte in path' };
  if (path.posix.isAbsolute(raw) || /^[a-zA-Z]:/.test(raw)) return { ok: false, reason: 'absolute path rejected' };
  const segments = raw.split('/').filter((s) => s !== '' && s !== '.');
  if (segments.some((s) => s === '..')) return { ok: false, reason: 'parent traversal rejected' };
  for (const seg of segments) {
    if (WINDOWS_DEVICE.test(seg)) return { ok: false, reason: `reserved device name rejected: ${seg}` };
  }
  const rootAbs = path.resolve(root);
  const abs = path.resolve(rootAbs, segments.join(path.sep));
  const relCheck = path.relative(rootAbs, abs);
  if (relCheck.startsWith('..') || path.isAbsolute(relCheck)) {
    return { ok: false, reason: 'escapes sandbox root' };
  }
  return { ok: true, abs };
}

/**
 * realpath 级越界检查。
 *
 * `resolveInside` 只做**词法**检查：`mirror/link.py` 这样的路径在字符串上完全
 * 合法，但 `link.py` 可能是一个指向 `C:\\Users\\...` 的符号链接 —— 模型读到
 * 的就是宿主机文件。词法检查无法发现这件事，只有 `realpath` 能。
 *
 * 返回解析后的真实路径：调用方应当用 `abs` 去 open，而不是原始路径，否则
 * 检查与使用之间存在 TOCTOU 窗口。
 */
export async function realInside(root: string, abs: string): Promise<GuardResult> {
  try {
    const realRoot = await fs.realpath(path.resolve(root));
    const realAbs = await fs.realpath(abs);
    const rel = path.relative(realRoot, realAbs);
    if (rel.startsWith('..') || path.isAbsolute(rel)) {
      return { ok: false, reason: 'symlink escapes sandbox root' };
    }
    return { ok: true, abs: realAbs };
  } catch (err) {
    return { ok: false, reason: `path not accessible: ${(err as Error).message}` };
  }
}

function clip(text: string, max: number): { text: string; truncated: boolean } {
  if (text.length <= max) return { text, truncated: false };
  return { text: `${text.slice(0, max)}\n…[truncated]`, truncated: true };
}

const LANGUAGE_BY_EXT: Record<string, string> = {
  '.py': 'python',
  '.ts': 'typescript',
  '.tsx': 'typescript',
  '.js': 'javascript',
  '.jsx': 'javascript',
  '.go': 'go',
  '.rs': 'rust',
  '.java': 'java',
  '.rb': 'ruby',
  '.md': 'markdown',
  '.json': 'json',
  '.toml': 'toml',
  '.yaml': 'yaml',
  '.yml': 'yaml',
  '.css': 'css',
  '.html': 'html',
  '.sh': 'shell',
};

/** 目录遍历的忽略集：与 `ingest/guard.py` 的忽略集保持一致，否则"树里有、读不到"。 */
const IGNORED_DIRS = new Set([
  '.git',
  'node_modules',
  '__pycache__',
  '.venv',
  'venv',
  'dist',
  'build',
  '.next',
  '.mypy_cache',
  '.pytest_cache',
  'target',
  '.idea',
  '.vscode',
]);

export interface TreeEntry {
  path: string;
  size: number;
  lang: string;
  is_core: boolean;
}

const CORE_EXT = new Set(['.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.java']);

/** 递归列树。深度上限 8、条目上限 400 —— 防止一个巨型 monorepo 把 token 烧光。 */
export async function listTree(root: string, maxDepth = 8): Promise<TreeEntry[]> {
  const out: TreeEntry[] = [];
  const walk = async (dirAbs: string, depth: number): Promise<void> => {
    if (depth > maxDepth || out.length >= MAX_TREE_ENTRIES) return;
    let entries;
    try {
      entries = await readdir(dirAbs, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (out.length >= MAX_TREE_ENTRIES) return;
      const abs = path.join(dirAbs, entry.name);
      const rel = path.relative(path.resolve(root), abs).replace(/\\/g, '/');
      if (entry.isDirectory()) {
        if (IGNORED_DIRS.has(entry.name)) continue;
        await walk(abs, depth + 1);
        continue;
      }
      if (!entry.isFile()) continue;
      const ext = path.extname(entry.name).toLowerCase();
      let size = 0;
      try {
        size = (await stat(abs)).size;
      } catch {
        size = 0;
      }
      out.push({ path: rel, size, lang: LANGUAGE_BY_EXT[ext] ?? 'text', is_core: CORE_EXT.has(ext) });
    }
  };
  await walk(path.resolve(root), 0);
  return out;
}

/**
 * 构造 4 个只读工具。
 *
 * `root` 在**闭包**里固定：模型无法通过参数改变沙箱根，这一点不能靠"参数校验"
 * 实现（那又变成可绕过的软约束）。
 */
export function createRepoTools(root: string) {
  const rootAbs = path.resolve(root);

  const repoListTree = defineTool({
    name: 'repo_list_tree',
    label: '列出仓库文件树',
    description:
      '列出仓库镜像中的文件与目录（已忽略 .git/node_modules 等）。返回 path/size/lang/is_core。' +
      '这是了解仓库结构的第一步；条目上限 400，超出会标记 truncated。',
    parameters: {
      type: 'object',
      properties: {
        subdir: { type: 'string', description: '限定子目录（相对路径），留空表示根目录' },
      },
      additionalProperties: false,
    },
    execute: async (_toolCallId: string, args: Record<string, unknown>) => {
      const subdir = typeof args.subdir === 'string' ? args.subdir : '';
      let base = rootAbs;
      if (subdir) {
        const r = resolveInside(rootAbs, subdir);
        if (!r.ok || !r.abs) return fail(`拒绝访问：${r.reason}`, { blocked: true });
        const real = await realInside(rootAbs, r.abs);
        if (!real.ok || !real.abs) return fail(`拒绝访问：${real.reason}`, { blocked: true });
        base = real.abs;
      }
      const all = await listTree(base);
      const prefix = subdir ? `${subdir.replace(/\\/g, '/').replace(/\/$/, '')}/` : '';
      const entries = all.map((e) => ({ ...e, path: `${prefix}${e.path}` }));
      return ok({
        entries,
        count: entries.length,
        truncated: entries.length >= MAX_TREE_ENTRIES,
      });
    },
  });

  const repoReadFile = defineTool({
    name: 'repo_read_file',
    label: '读取仓库文件',
    description:
      '读取仓库镜像中某个文件的内容。路径必须是相对镜像根的路径；单文件上限 256KB，超出截断并标记 truncated。' +
      '不要在无法确定路径时猜，先用 repo_list_tree 或 repo_grep 定位。',
    parameters: {
      type: 'object',
      properties: {
        file: { type: 'string', description: '相对路径，例如 repolearn/core/config.py' },
        line_start: { type: 'number', description: '可选，起始行（1-based）' },
        line_end: { type: 'number', description: '可选，结束行（含）' },
      },
      required: ['file'],
      additionalProperties: false,
    },
    execute: async (_toolCallId: string, args: Record<string, unknown>) => {
      const file = typeof args.file === 'string' ? args.file : '';
      const r = resolveInside(rootAbs, file);
      if (!r.ok || !r.abs) return fail(`拒绝访问：${r.reason}`, { blocked: true });
      const real = await realInside(rootAbs, r.abs);
      if (!real.ok || !real.abs) return fail(`拒绝访问：${real.reason}`, { blocked: true });
      let buf: Buffer;
      try {
        buf = await readFile(real.abs);
      } catch {
        return fail(`文件不存在或不可读：${file}`, { notFound: true });
      }
      const clipped = buf.subarray(0, MAX_FILE_BYTES);
      let content = clipped.toString('utf8');
      const truncatedBySize = buf.length > MAX_FILE_BYTES;
      const lineStart = typeof args.line_start === 'number' ? Math.max(1, args.line_start) : null;
      const lineEnd = typeof args.line_end === 'number' ? args.line_end : null;
      let offset = 0;
      if (lineStart !== null) {
        const lines = content.split('\n');
        offset = lineStart - 1;
        const end = lineEnd !== null ? lineEnd : lines.length;
        content = lines.slice(offset, end).join('\n');
      }
      const c = clip(content, MAX_FILE_BYTES);
      return ok({
        file,
        lang: LANGUAGE_BY_EXT[path.extname(file).toLowerCase()] ?? 'text',
        total_bytes: buf.length,
        line_offset: offset,
        content: c.text,
        truncated: c.truncated || truncatedBySize || content !== c.text,
      });
    },
  });

  const repoGrep = defineTool({
    name: 'repo_grep',
    label: '在仓库中搜索',
    description:
      '在仓库镜像的文本文件中做正则搜索（大小写不敏感）。返回 file/line/text，最多 200 条。' +
      '用于定位符号定义与调用点；不要用它在整个仓库里找随机词，先收窄 pattern。',
    parameters: {
      type: 'object',
      properties: {
        pattern: { type: 'string', description: 'JavaScript 正则表达式' },
        glob: { type: 'string', description: '可选，文件名后缀过滤，例如 .py' },
        limit: { type: 'number', description: '返回条数上限（≤200）' },
      },
      required: ['pattern'],
      additionalProperties: false,
    },
    execute: async (_toolCallId: string, args: Record<string, unknown>) => {
      const patternSrc = typeof args.pattern === 'string' ? args.pattern : '';
      if (!patternSrc) return fail('pattern 不能为空', { matches: [] });
      let re: RegExp;
      try {
        re = new RegExp(patternSrc, 'i');
      } catch (err) {
        return fail(`正则无效：${(err as Error).message}`, { matches: [] });
      }
      const suffix = typeof args.glob === 'string' ? args.glob : '';
      const limit = Math.min(typeof args.limit === 'number' ? args.limit : 50, MAX_GREP_MATCHES);
      const tree = await listTree(rootAbs);
      const matches: Array<{ file: string; line: number; text: string }> = [];
      for (const entry of tree) {
        if (matches.length >= limit) break;
        if (suffix && !entry.path.endsWith(suffix)) continue;
        if (entry.size > MAX_FILE_BYTES) continue;
        const r = resolveInside(rootAbs, entry.path);
        if (!r.ok || !r.abs) continue;
        let text: string;
        try {
          text = await readFile(r.abs, 'utf8');
        } catch {
          continue;
        }
        const lines = text.split('\n');
        for (let i = 0; i < lines.length; i += 1) {
          if (matches.length >= limit) break;
          const line = lines[i] ?? '';
          if (re.test(line)) {
            matches.push({ file: entry.path, line: i + 1, text: line.slice(0, 300) });
          }
        }
      }
      return ok({ matches, count: matches.length, truncated: matches.length >= limit });
    },
  });

  const repoFileOutline = defineTool({
    name: 'repo_file_outline',
    label: '提取文件符号大纲',
    description:
      '用正则提取一个文件里的顶层符号（class/def/function/const/interface 等）与所在行号。' +
      '用于在不读整份文件的情况下判断"该看哪几行"。',
    parameters: {
      type: 'object',
      properties: { file: { type: 'string', description: '相对路径' } },
      required: ['file'],
      additionalProperties: false,
    },
    execute: async (_toolCallId: string, args: Record<string, unknown>) => {
      const file = typeof args.file === 'string' ? args.file : '';
      const r = resolveInside(rootAbs, file);
      if (!r.ok || !r.abs) return fail(`拒绝访问：${r.reason}`, { blocked: true });
      const real = await realInside(rootAbs, r.abs);
      if (!real.ok || !real.abs) return fail(`拒绝访问：${real.reason}`, { blocked: true });
      let text: string;
      try {
        text = (await readFile(real.abs)).subarray(0, MAX_FILE_BYTES).toString('utf8');
      } catch {
        return fail(`文件不存在或不可读：${file}`, { notFound: true });
      }
      const symbols = outlineSymbols(text);
      return ok({ file, symbols, count: symbols.length });
    },
  });

  return [repoListTree, repoReadFile, repoGrep, repoFileOutline];
}

export interface OutlineSymbol {
  name: string;
  kind: 'class' | 'function' | 'const' | 'interface' | 'type' | 'method';
  line: number;
}

const OUTLINE_PATTERNS: Array<{ re: RegExp; kind: OutlineSymbol['kind'] }> = [
  { re: /^(\s*)class\s+([A-Za-z_$][\w$]*)/, kind: 'class' },
  { re: /^(\s*)(?:async\s+)?def\s+([A-Za-z_]\w*)/, kind: 'function' },
  { re: /^(\s*)(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/, kind: 'function' },
  { re: /^(\s*)(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(/, kind: 'function' },
  { re: /^(\s*)(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)/, kind: 'interface' },
  { re: /^(\s*)(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*=/, kind: 'type' },
  { re: /^(\s*)func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)/, kind: 'function' },
  { re: /^(\s*)(?:pub\s+)?fn\s+([A-Za-z_]\w*)/, kind: 'function' },
];

/** 纯函数，便于单测：正则大纲抽取（tree-sitter 缺失时的退化路径，spec §3.4 N4）。 */
export function outlineSymbols(text: string): OutlineSymbol[] {
  const out: OutlineSymbol[] = [];
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i] ?? '';
    if (line.length > 400) continue;
    for (const { re, kind } of OUTLINE_PATTERNS) {
      const m = re.exec(line);
      if (m) {
        const name = m[2];
        if (name && !name.startsWith('__')) {
          out.push({ name, kind, line: i + 1 });
        }
        break;
      }
    }
  }
  return out;
}
