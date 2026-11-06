/**
 * Gate 0 三态探测（Node 版）—— spec §3.2.4 / §4.6 #83 / §7.6。
 *
 * 用法：
 *
 *     node scripts/probe_gates.mjs                    # 写 <run-dir>/preflight.json
 *     node scripts/probe_gates.mjs --print            # 写文件 + 把同一份 JSON 打到 stdout
 *     node scripts/probe_gates.mjs --out <path>       # 写到指定路径（可与 --print 同用）
 *     node scripts/probe_gates.mjs --run-dir <dir>    # 只在没给 --out 时生效
 *
 * run-dir 的优先级：`--run-dir` > env `REPOLEARN_RUN_DIR` > `<repo>/.run`
 * （与 `apps/api/repolearn/core/config.py` 的 `Settings.run_dir` 同义）。
 *
 * ## JSON 形状：以 `scripts/check_env.ps1` 为准，一个字都不多
 *
 * check_env.ps1 写出的 `.run/preflight.json` 是既有真源——`/healthz.gates`
 * （`apps/api/repolearn/routers/health.py`）读的就是它。所以这里输出：
 *
 *     {
 *       "node": "v22.6.0", "python": "Python 3.12.4", "npm": "10.8.1", "pnpm": "12.18.0",
 *       "gates":  { "g1": "ok|missing|unknown", "g2": "...", "g3": "..." },
 *       "detail": { "g1": "...", "g2": "...", "g3": "..." }
 *     }
 *
 * 刻意的取舍（避免"两份实现、两个形状"）：
 *
 * 1. **没有 `at` / 时间戳字段**。check_env.ps1 不写，这里就不写；多一个字段就等于
 *    "形状不一致"，而 health.py 只读 `gates`，加了也只是噪声。
 * 2. **三态取值域只有 `ok` / `missing` / `unknown`**：
 *      - `ok`      —— 探测到了，且可用；
 *      - `missing` —— 探测跑完、结论是"没有"（这是确定结论，不是失败）；
 *      - `unknown` —— 探测本身没跑成（读不到 / 超时 / 抛异常）。**不能**把
 *                     "不知道"写成 `missing`：e2e 的 `book-and-degrade` 先断言
 *                     `g2 !== "unknown"`，再把 PDF 入口与 `g2` 对齐；把未知写成
 *                     missing 会让那条断言靠"什么都没探测到"蒙过去。
 * 3. **文件不带 BOM**。health.py 用 `utf-8-sig` 读，有无 BOM 都能解析；PowerShell
 *    那份会带 BOM（PS 5.1 的 `-Encoding UTF8`），这里没必要跟着。
 * 4. 顶层 `node` / `python` / `npm` / `pnpm` 与 check_env.ps1 一样是**版本字符串或
 *    null**（命令不存在 = null，命令在但跑不出来 = `"unknown"`）。一点已知差异：
 *    Windows 上 npm/pnpm 是 `.cmd` 垫片，必须经 `shell: true` 启动（Node 22 起直接
 *    spawn `.cmd` 会抛 EINVAL）。此路径下"命令不存在"由 cmd 报 `not recognized`
 *    而不是 ENOENT，因此会显示成 `"unknown"` 而非 null——两者都不影响 `gates`。
 *
 * ## 判据
 *
 * - `g1` = agent core：`services/agent-kernel/node_modules/@aragon-agent/core/package.json`
 *   存在且可读（会向上走到仓库根的 `node_modules`，pnpm 的软链与 hoist 都能命中）。
 *   比 check_env.ps1 松一点：那一份会经 `scripts/probe_core.mjs` 真的 import 一次。
 *   差异只在"装了但装坏"这一种情形，而修复动作与"没装"完全相同（重装）。
 * - `g2` = chromium：`<web>/node_modules/playwright` 或 `ms-playwright` 缓存目录
 *   （`%LOCALAPPDATA%\ms-playwright` / `~/.cache/ms-playwright` / macOS 的
 *   `~/Library/Caches/ms-playwright`，以及显式配置的 `PLAYWRIGHT_BROWSERS_PATH`）
 *   下有没有 `chromium*` 目录。目录读不到 → `unknown`。
 * - `g3` = tree-sitter：`python -c "import tree_sitter_language_pack"` 的退出码。
 *   python 优先用仓库的 `.venv`（与 check_env.ps1 一致），否则用 PATH 上的 python。
 *
 * ## 硬超时与退出码
 *
 * 每个外部命令都用 `spawnSync` 的 `timeout`（10s）兜住：Gate 0 在任何情况下
 * 都不许把 `e2e-real` 或 CI 卡住。**退出码永远是 0**——探测结论属于数据，
 * 不属于失败；只有参数非法才退出 2。
 *
 * 注意：默认路径会覆盖开发机的 `.run/preflight.json`（与 check_env.ps1 同一份，
 * 两份结论应当一致）。`e2e-real` 用 `REPOLEARN_RUN_DIR` / `--out` 把它隔离到
 * `var/e2e/<runId>/run/`。
 */

import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..');
const KERNEL_DIR = join(REPO_ROOT, 'services', 'agent-kernel');
const WEB_DIR = join(REPO_ROOT, 'apps', 'web');

/** 单个外部探测的硬超时。10s 足够任何一次 `--version` / import，又远小于任何 CI 步骤。 */
const PROBE_TIMEOUT_MS = 10_000;

const CORE_SCOPE = '@aragon-agent';
const CORE_NAME = 'core';
const CORE_MANIFEST_TAIL = ['node_modules', CORE_SCOPE, CORE_NAME, 'package.json'];

const USAGE = `用法: node scripts/probe_gates.mjs [--print] [--out <path>] [--run-dir <dir>]`;

function parseArgs(argv) {
  const opts = { print: false, out: null, runDir: null, help: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--print') {
      opts.print = true;
      continue;
    }
    if (arg === '--help' || arg === '-h') {
      opts.help = true;
      continue;
    }
    if (arg === '--out' || arg === '--run-dir') {
      const value = argv[i + 1];
      if (!value || value.startsWith('--')) throw new Error(`${arg} 需要一个路径参数`);
      if (arg === '--out') opts.out = resolve(value);
      else opts.runDir = resolve(value);
      i += 1;
      continue;
    }
    throw new Error(`未知参数：${arg}`);
  }
  return opts;
}

/** 单行化 + 截断：detail 最终会出现在 `/healthz.gates` 与 CI 日志里，不能是多行堆栈。 */
function oneLine(value, limit = 200) {
  const text = String(value ?? '')
    .split(/\r?\n/)
    .map((part) => part.trim())
    .filter(Boolean)
    .join(' | ');
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function lastLine(value) {
  const lines = String(value ?? '')
    .split(/\r?\n/)
    .map((part) => part.trim())
    .filter(Boolean);
  return lines.length > 0 ? oneLine(lines[lines.length - 1]) : '';
}

/**
 * 跑一个外部命令并保证有硬超时。
 *
 * 返回值刻意区分三种"没成功"：`notFound`（命令不存在）、`timedOut`（超时被杀）、
 * 其它错误。前两种的处置不同（不存在 → 确定结论；超时 → `unknown`）。
 */
function run(cmd, args, timeout = PROBE_TIMEOUT_MS, extra = {}) {
  const result = { status: null, stdout: '', stderr: '', error: null, timedOut: false, notFound: false };
  try {
    const child = spawnSync(cmd, args, {
      encoding: 'utf8',
      timeout,
      windowsHide: true,
      maxBuffer: 1024 * 1024,
      ...extra,
    });
    result.status = child.status;
    result.stdout = (child.stdout ?? '').trim();
    result.stderr = (child.stderr ?? '').trim();
    if (child.error) {
      result.error = child.error;
      result.notFound = child.error.code === 'ENOENT';
      // spawnSync 超时既可能带 ETIMEDOUT，也可能只留一个信号；两种都算超时。
      result.timedOut = child.error.code === 'ETIMEDOUT' || Boolean(child.signal);
    }
  } catch (err) {
    // 兜底：spawnSync 本身抛异常（例如参数非法）也不许让探针崩。
    result.error = err;
    result.notFound = err?.code === 'ENOENT';
  }
  return result;
}

function probeVersion(cmd, args) {
  // Windows 上 npm / pnpm 是 `.cmd` 垫片，不是 PE 文件：Node 22 起直接
  // spawnSync('.cmd') 会抛 EINVAL（CVE-2024-27980 之后的加固），必须交给 shell 解析。
  // 若 shell 也起不来，这里会落到 `'unknown'` 而不是 null——"命令在但跑不出来"
  // 与"命令不存在"是两件不同的事，detail 里不该混为一谈。
  const r = run(cmd, args, PROBE_TIMEOUT_MS, { shell: process.platform === 'win32' });
  if (r.notFound) return null; // check_env.ps1 在"命令不存在"时也是 null
  if (r.timedOut || (r.error && !r.notFound)) return 'unknown';
  const line = (r.stdout || r.stderr || '').split(/\r?\n/)[0]?.trim();
  return line || 'unknown';
}

function resolvePython() {
  const candidates =
    process.platform === 'win32'
      ? [join(REPO_ROOT, '.venv', 'Scripts', 'python.exe')]
      : [join(REPO_ROOT, '.venv', 'bin', 'python')];
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return 'python';
}

/** 向上找 `node_modules/@aragon-agent/core/package.json`（pnpm 软链 / hoist 都能命中）。 */
function findCoreManifest(startDir) {
  let dir = startDir;
  for (let i = 0; i < 12; i += 1) {
    const candidate = join(dir, ...CORE_MANIFEST_TAIL);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function probeG1() {
  try {
    const manifestPath = findCoreManifest(KERNEL_DIR);
    if (!manifestPath) {
      return {
        state: 'missing',
        detail: `${CORE_SCOPE}/${CORE_NAME} not installed under ${KERNEL_DIR} (run: pnpm -C services/agent-kernel install) -> template fallback, course will be simplified`,
      };
    }
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
    return { state: 'ok', detail: `${CORE_SCOPE}/${CORE_NAME} ${manifest.version ?? 'unknown-version'}` };
  } catch (err) {
    // 清单读到了但读不出来（权限 / JSON 坏了）属于"探测失败"，不是"没有装"。
    return { state: 'unknown', detail: `probe failed: ${oneLine(err?.message ?? err)}` };
  }
}

function chromiumRoots() {
  const roots = [];
  const fromEnv = (process.env.PLAYWRIGHT_BROWSERS_PATH ?? '').trim();
  if (fromEnv && fromEnv !== '0') roots.push(fromEnv);
  if (process.platform === 'win32') {
    const localAppData = (process.env.LOCALAPPDATA ?? '').trim();
    if (localAppData) roots.push(join(localAppData, 'ms-playwright'));
  } else if (process.platform === 'darwin') {
    roots.push(join(homedir(), 'Library', 'Caches', 'ms-playwright'));
  } else {
    roots.push(join(homedir(), '.cache', 'ms-playwright'));
  }
  return roots;
}

function probeG2(python) {
  // 判据**只能有一个**：产品自己那句判断。`rendering/pdf.py::chromium_available()`
  // 用 Python playwright 真 launch 一次；而"ms-playwright 缓存里有 chromium 目录"
  // 只说明 **Node** 侧装过浏览器——两边 revision 不保证一致（CI 只跑
  // `npx playwright install chromium`），于是会出现 g2=ok 而 PDF 导出降级成打印
  // 视图。两个判据给出两个结论时，`book-and-degrade` 只能靠 `unknown` 蒙过去
  // （spec R16 登记的复核点）。缓存目录降级为 detail 里的旁证，不参与判定。
  const cacheHint = chromiumCacheHint();
  const r = run(
    python,
    [
      '-c',
      // 一行 Python：把仓库的 apps/api 放进 sys.path（venv 里是 editable 安装，
      // 但显式加一次可以让"没 pip install -e"的开发机也能得到同一个结论），
      // 然后调用产品自己的判据。
      'import sys;sys.path.insert(0,"apps/api");from repolearn.rendering.pdf import chromium_available;print("OK" if chromium_available() else "NO")',
    ],
    120_000,
    { cwd: REPO_ROOT },
  );
  if (r.notFound) {
    return {
      state: 'missing',
      detail: `python not found (${python}); run: python -m playwright install chromium  (else PDF export falls back to a print view)`,
    };
  }
  if (r.timedOut) {
    return { state: 'unknown', detail: `probe timed out: ${python} 未在预算内返回（chromium launch 卡住）` };
  }
  if (r.error) {
    return { state: 'unknown', detail: `probe failed: ${oneLine(r.error?.message ?? r.error)}` };
  }
  if (r.status === 0 && r.stdout.includes('OK')) {
    return { state: 'ok', detail: `chromium launchable by python playwright（${cacheHint}）` };
  }
  if (r.status === 0 && r.stdout.includes('NO')) {
    return {
      state: 'missing',
      detail: `python playwright cannot launch chromium（${cacheHint}）; run: python -m playwright install chromium  (else PDF export falls back to a print view)`,
    };
  }
  const tail = lastLine(r.stderr || r.stdout) || `exit ${r.status}`;
  return { state: 'unknown', detail: `probe failed: ${tail}（${cacheHint}）` };
}

/** 缓存目录只作为 detail 的旁证，不参与 g2 的判定（判定见 `probeG2`）。 */
function chromiumCacheHint() {
  for (const root of chromiumRoots()) {
    if (!existsSync(root)) continue;
    try {
      const bundles = readdirSync(root, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && entry.name.startsWith('chromium'))
        .map((entry) => entry.name)
        .sort();
      if (bundles.length > 0) return `ms-playwright: ${root} → ${bundles.join(', ')}`;
    } catch {
      continue;
    }
  }
  return 'ms-playwright: 未见 chromium 目录';
}

function probeG3(python) {
  const r = run(python, ['-c', 'import tree_sitter_language_pack; print("OK")']);
  if (r.timedOut) {
    return { state: 'unknown', detail: `probe timed out after ${PROBE_TIMEOUT_MS}ms: ${python}` };
  }
  if (r.notFound) {
    return {
      state: 'missing',
      detail: `python not found (${python}); run: .venv\\Scripts\\pip install tree-sitter-language-pack  (else anchors fall back to regex)`,
    };
  }
  if (r.error) {
    return { state: 'unknown', detail: `probe failed: ${oneLine(r.error?.message ?? r.error)}` };
  }
  if (r.status === 0 && r.stdout.includes('OK')) {
    return { state: 'ok', detail: 'tree-sitter-language-pack available' };
  }
  const tail = lastLine(r.stderr || r.stdout) || `exit ${r.status}`;
  return {
    state: 'missing',
    detail: `run: .venv\\Scripts\\pip install tree-sitter-language-pack  (else anchors fall back to regex) | ${tail}`,
  };
}

function main(argv) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (err) {
    process.stderr.write(`${oneLine(err?.message ?? err)}\n${USAGE}\n`);
    return 2;
  }
  if (opts.help) {
    process.stdout.write(`${USAGE}\n`);
    return 0;
  }

  const python = resolvePython();
  const g1 = probeG1();
  const g2 = probeG2(python);
  const g3 = probeG3(python);

  // 键顺序刻意与 check_env.ps1 的 `$result` 一致，方便人眼 diff 两份文件。
  const payload = {
    node: process.version,
    python: probeVersion(python, ['--version']),
    npm: probeVersion('npm', ['--version']),
    pnpm: probeVersion('pnpm', ['--version']),
    gates: { g1: g1.state, g2: g2.state, g3: g3.state },
    detail: { g1: g1.detail, g2: g2.detail, g3: g3.detail },
  };

  const runDir =
    opts.runDir ||
    ((process.env.REPOLEARN_RUN_DIR ?? '').trim()
      ? resolve((process.env.REPOLEARN_RUN_DIR ?? '').trim())
      : join(REPO_ROOT, '.run'));
  const outPath = opts.out || join(runDir, 'preflight.json');

  const body = `${JSON.stringify(payload, null, 2)}\n`;
  try {
    mkdirSync(dirname(outPath), { recursive: true });
    writeFileSync(outPath, body, 'utf8');
  } catch (err) {
    // 写不进去不算探针失败：三态结论仍然可以打印出来（e2e-real 会自己看文件，
    // 但 `--print` 的调用方不该因为只读目录而拿不到数据）。
    process.stderr.write(`无法写入 ${outPath}: ${oneLine(err?.message ?? err)}\n`);
  }

  if (opts.print) process.stdout.write(body);
  return 0;
}

process.exitCode = main(process.argv.slice(2));
