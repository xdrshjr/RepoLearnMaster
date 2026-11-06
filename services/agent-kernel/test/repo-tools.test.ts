/**
 * T-KRN-5 / T-SEC-3：工具层的路径越界与截断策略。
 *
 * 这些是**安全断言**，不是功能断言：一条通过意味着 `../../secret` 不会被读到。
 */
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { createRepoTools, outlineSymbols, resolveInside } from '../src/tools/repo.ts';
import { readPayload, type ToolResultLike } from '../src/tools/result.ts';

interface RawTool {
  name: string;
  execute: (toolCallId: string, params: Record<string, unknown>, context: object) => Promise<ToolResultLike>;
}

function pick(tools: unknown[], name: string): RawTool {
  const found = tools.find((t) => (t as { name: string }).name === name) as RawTool | undefined;
  assert.ok(found, `tool ${name} missing`);
  return found;
}

async function call(tools: unknown[], name: string, params: Record<string, unknown>) {
  const tool = pick(tools, name);
  const result = await tool.execute('call-1', params, {});
  return { result, payload: readPayload(result) };
}

async function makeMirror(): Promise<string> {
  const root = await mkdtemp(path.join(tmpdir(), 'rl-mirror-'));
  await mkdir(path.join(root, 'pkg'), { recursive: true });
  await writeFile(path.join(root, 'pkg', 'mod.py'), 'def alpha():\n    return 1\n\nclass Beta:\n    pass\n', 'utf8');
  await writeFile(path.join(root, 'README.md'), '# demo\n', 'utf8');
  await writeFile(path.join(tmpdir(), 'outside-secret.txt'), 'TOP SECRET', 'utf8');
  return root;
}

test('resolveInside 拒绝父目录穿越', () => {
  const r = resolveInside('C:/mirror', '../../etc/passwd');
  assert.equal(r.ok, false);
  assert.match(r.reason ?? '', /parent traversal/);
});

test('resolveInside 拒绝绝对路径', () => {
  assert.equal(resolveInside('C:/mirror', '/etc/passwd').ok, false);
  assert.equal(resolveInside('C:/mirror', 'C:/Windows/win.ini').ok, false);
});

test('resolveInside 拒绝 Windows 设备名（T-SEC-2 同类风险）', () => {
  const r = resolveInside('C:/mirror', 'pkg/CON');
  assert.equal(r.ok, false);
  assert.match(r.reason ?? '', /reserved device/);
});

test('resolveInside 接受正常相对路径', () => {
  const r = resolveInside('C:/mirror', 'pkg/mod.py');
  assert.equal(r.ok, true);
  assert.ok((r.abs ?? '').endsWith('mod.py'));
});

test('repo_read_file 越界返回错误结果而不是内容', async () => {
  const root = await makeMirror();
  const tools = createRepoTools(root);
  const { result, payload } = await call(tools, 'repo_read_file', { file: '../../outside-secret.txt' });
  assert.equal(result.isError, true);
  assert.equal(payload.blocked, true);
  assert.equal(payload.content, undefined);
  assert.equal(JSON.stringify(result).includes('TOP SECRET'), false);
});

test('repo_read_file 正常读取并给出 lang', async () => {
  const root = await makeMirror();
  const tools = createRepoTools(root);
  const { payload } = await call(tools, 'repo_read_file', { file: 'pkg/mod.py' });
  assert.equal(payload.lang, 'python');
  assert.match(String(payload.content), /def alpha/);
  assert.equal(payload.truncated, false);
});

test('repo_list_tree 忽略 .git 与 node_modules', async () => {
  const root = await makeMirror();
  await mkdir(path.join(root, '.git'), { recursive: true });
  await writeFile(path.join(root, '.git', 'config'), 'x', 'utf8');
  await mkdir(path.join(root, 'node_modules', 'x'), { recursive: true });
  const tools = createRepoTools(root);
  const { payload } = await call(tools, 'repo_list_tree', {});
  const paths = (payload.entries as Array<{ path: string }>).map((e) => e.path);
  assert.ok(paths.includes('pkg/mod.py'));
  assert.equal(paths.some((p) => p.startsWith('.git/')), false);
  assert.equal(paths.some((p) => p.startsWith('node_modules/')), false);
});

test('repo_grep 命中行号且受 limit 约束', async () => {
  const root = await makeMirror();
  const tools = createRepoTools(root);
  const { payload } = await call(tools, 'repo_grep', { pattern: 'def alpha', limit: 5 });
  const matches = payload.matches as Array<{ file: string; line: number }>;
  assert.equal(matches.length, 1);
  assert.equal(matches[0]?.file, 'pkg/mod.py');
  assert.equal(matches[0]?.line, 1);
});

test('repo_file_outline 抽出类与函数', async () => {
  const root = await makeMirror();
  const tools = createRepoTools(root);
  const { payload } = await call(tools, 'repo_file_outline', { file: 'pkg/mod.py' });
  const symbols = payload.symbols as Array<{ name: string; kind: string }>;
  assert.deepEqual(
    symbols.map((s) => `${s.kind}:${s.name}`),
    ['function:alpha', 'class:Beta'],
  );
});

test('outlineSymbols 支持多语言常见形态', () => {
  const ts = 'export function run() {}\nexport interface Foo {}\nexport const bar = async () => {}\n';
  const kinds = outlineSymbols(ts).map((s) => `${s.kind}:${s.name}`);
  assert.ok(kinds.includes('function:run'));
  assert.ok(kinds.includes('interface:Foo'));
  assert.ok(kinds.includes('function:bar'));
});

test('符号链接指向外部时读取被拒绝（realpath 级沙箱）', async () => {
  const root = await makeMirror();
  const outside = path.join(await mkdtemp(path.join(tmpdir(), 'rl-outside-')), 'outside-secret.txt');
  await writeFile(outside, 'TOP-SECRET-PAYLOAD');
  const linkPath = path.join(root, 'pkg', 'escape.txt');
  try {
    await symlink(outside, linkPath);
  } catch {
    return; // 无权限创建符号链接（Windows 非开发者模式下常见）→ 跳过
  }
  const tools = createRepoTools(root);
  const { payload } = await call(tools, 'repo_read_file', { file: 'pkg/escape.txt' });
  // 词法检查认为它在沙箱内，只有 realpath 能发现它指向宿主机文件。
  assert.equal(payload.blocked, true);
  assert.equal(payload.content, undefined);
});

test('符号链接指向沙箱内部时仍然可读（守卫不是一味拒绝）', async () => {
  const root = await makeMirror();
  const realPath = path.join(root, 'pkg', 'mod.py');
  const linkPath = path.join(root, 'pkg', 'alias.py');
  try {
    await symlink(realPath, linkPath);
  } catch {
    return;
  }
  const tools = createRepoTools(root);
  const { payload } = await call(tools, 'repo_read_file', { file: 'pkg/alias.py' });
  assert.equal(typeof payload.content, 'string');
  assert.ok(String(payload.content).length > 0);
});
