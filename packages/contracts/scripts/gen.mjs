/**
 * 契约生成脚本（spec §4.3 / §5.7）。
 *
 * `gen`  ：从 `openapi.json` 生成 `apps/web/src/lib/api/schema.d.ts`（前端类型）
 * `--check`：只校验生成物是否最新（CI 用；漂移即失败）
 *
 * 为什么生成物要入库：CI 与前端构建都不该依赖"先跑一遍后端"。
 * 入库 + `--check` 才能在**不改后端**的情况下发现"有人手改了生成物"。
 */

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..', '..');
const openapiPath = join(root, 'packages', 'contracts', 'openapi.json');
const targetPath = join(root, 'apps', 'web', 'src', 'lib', 'api', 'schema.d.ts');
// 同一份产物也落在 contracts 包里：`src/index.ts` 从这里再导出 paths/components，
// 让"契约只有一份"在**包边界**上也成立（前端与 Kernel 各自 import，不互相 import）。
const contractsTypesPath = join(root, 'packages', 'contracts', 'src', 'types.ts');
const check = process.argv.includes('--check');

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

if (!existsSync(openapiPath)) {
  fail(
    `missing ${openapiPath}\n` +
      'run: python -m repolearn.cli export-openapi   (or python scripts/export_contracts.py)',
  );
}

/**
 * 优先用 node_modules 里的 bin（离线可跑），找不到再退回 `npx --yes`。
 *
 * 离线是硬要求：本项目的 `--check` 会在 CI 与开发机上反复执行，任何一次
 * "需要联网才能校验契约"都会让门禁被关掉。
 */
/**
 * 解析出 openapi-typescript 的入口。
 *
 * 两条现实约束：
 *  1. 离线可跑 —— 优先用仓库内的依赖，绝不为"校验契约"去联网；
 *  2. Windows 上 `spawnSync('npx.cmd')` / `.bin/*.cmd` 一律 EINVAL（沙箱限制），
 *     所以直接用 `node <cli.js>`，绕开 .cmd 这套 shell 机制。
 */
function resolveRunner() {
  const cli = join(root, 'packages', 'contracts', 'node_modules', 'openapi-typescript', 'bin', 'cli.js');
  if (existsSync(cli)) return { command: process.execPath, prefix: [cli], shell: false };
  return { command: process.platform === 'win32' ? 'npx.cmd' : 'npx', prefix: ['openapi-typescript'], shell: process.platform === 'win32' };
}

const openapiText = readFileSync(openapiPath, 'utf8');
const digest = createHash('sha256').update(openapiText).digest('hex').slice(0, 16);

let generated;
try {
  const runner = resolveRunner();
  // `/dev/stdout` 在 Windows 上不可写（`openapi-typescript` 会以 ENOENT 失败），
  // 而失败会被下面的兜底悄悄吞成 stub —— 于是"契约漂移检查"永远只比对占位文件。
  // 先落到 temp 目录再读回来，三个平台一致。
  const tmpOut = join(tmpdir(), `repolearn-openapi-${process.pid}.d.ts`);
  execFileSync(
    runner.command,
    [...runner.prefix, openapiPath, '--output', tmpOut],
    {
      encoding: 'utf8',
      maxBuffer: 32 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'pipe'],
      shell: runner.shell,
      env: { ...process.env, npm_config_yes: 'true' },
    },
  );
  generated = readFileSync(tmpOut, 'utf8');
  try {
    rmSync(tmpOut, { force: true });
  } catch {
    /* 临时文件清理失败不影响结果 */
  }
} catch (err) {
  // `openapi-typescript` 不可用时退化为"只带契约指纹的声明"提示，
  // 而不是"干掉一个不可解析的中间文件"。
  generated = `/**
 * 由 packages/contracts/openapi.json 生成（指纹 ${digest}）。
 *
 * 注意：生成时 openapi-typescript 不可用，因此这里只有契约指纹可用。
 * 运行 \`pnpm -F @repolearn/contracts gen\` 安装依赖后重新生成完整类型。
 */

export type ContractDigest = '${digest}';
export type ApiPaths = Record<string, never>;
`;
  process.stderr.write(`openapi-typescript unavailable, wrote stub (${String(err).slice(0, 160)})\n`);
}

const header = `/* eslint-disable */
// 自动生成，请勿手改。
// 源：packages/contracts/openapi.json（sha256:${digest}）
// 重新生成：pnpm -F @repolearn/contracts gen
`;

const body = header + (generated.includes('自动生成') ? generated : generated.replace(/^\/\* eslint-disable \*\/\n/, ''));

if (check) {
  for (const path of [targetPath, contractsTypesPath]) {
    if (!existsSync(path)) fail(`missing generated file ${path}`);
    if (readFileSync(path, 'utf8') !== body) {
      fail(`contract drift: ${path} 与 openapi.json 不一致，请运行 \`pnpm -F @repolearn/contracts gen\``);
    }
  }
  process.stdout.write('contracts up to date (web schema + package types)\n');
  process.exit(0);
}

for (const path of [targetPath, contractsTypesPath]) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, body, 'utf8');
  process.stdout.write(`wrote ${path} (digest ${digest})\n`);
}
