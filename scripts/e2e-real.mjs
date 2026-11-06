#!/usr/bin/env node
/**
 * real-backend E2E 编排（hardening spec §3.2.3，固定八步 + 第 5.5 步）。
 *
 * 用法：
 *
 *     node scripts/e2e-real.mjs                        # 四条用例全跑
 *     node scripts/e2e-real.mjs --spec import-to-lesson
 *     node scripts/e2e-real.mjs --keep                 # 保留本轮目录（排查用）
 *     node scripts/e2e-real.mjs --web-port 3101 --api-port 8101 --fake-port 9912
 *
 * 端口可用环境变量覆盖：`E2E_WEB_PORT` / `E2E_API_PORT` / `E2E_FAKE_PORT`。
 *
 * 退出码（三个，不多不少）：
 * * `0` 全绿；
 * * `1` 有用例失败（产品/断言问题）；
 * * `2` 环境不可用（端口被占、`.venv` 缺失、迁移失败、进程没在超时内就绪）。
 *
 * ## 为什么不是 PowerShell（spec §3.2.3 开篇）
 *
 * `start.ps1` 已经证明 PS 5.1 能起三进程，但它依赖 `.env` 与固定端口。E2E 需要
 * **每一轮都隔离**（端口、DB、对象目录、日志、Gate 0 结论）且跑完必须收干净；
 * Node 在 Windows/cmd、Linux、CI 三处行为一致，仓库里已有先例（`probe_gates.mjs`）。
 *
 * ## 为什么端口被占就退出，而不是自动换端口
 *
 * 自动换端口会把"为什么 CI 跑的是 3101"变成一个新的谜，而且会让两个并发跑的
 * e2e 互相污染对方的数据目录却仍然全绿。端口是环境的一部分，冲突就是环境没清干净，
 * 应当由人跑一次 `.\stop.ps1`，而不是由脚本偷偷绕过去。
 *
 * ## 为什么不用 Playwright 的 `webServer`
 *
 * `webServer` 的生命周期归 Playwright：它只在测试进程内起一个进程，既管不了
 * FastAPI 与假 GitHub，也无法在 `taskkill /T /F` 这一层收干净子树。三进程的
 * 启动顺序、就绪判定与清理必须在一个地方，否则"哪条是真门禁"会长期模糊。
 */

import { spawn, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import {
  createWriteStream,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import net from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..');
const WEB_DIR = join(REPO_ROOT, 'apps', 'web');
const API_DIR = join(REPO_ROOT, 'apps', 'api');
const E2E_ROOT = join(REPO_ROOT, 'var', 'e2e');

/** P2-6②：单个日志文件的硬上限。超过之后写一行 `[truncated]` 并停止写入。 */
const LOG_CAP_BYTES = 5 * 1024 * 1024;
/** P2-6③：只保留最近 N 轮目录，其余在开跑前删掉。 */
const KEEP_RUNS = 5;
/** 超时时要打印的日志尾巴行数（spec 第 7 步）。 */
const TAIL_LINES = 80;

/** 四条 P0 用例（spec §3.2.3 表 / §7.2 T-E2E-R1..R4）。 */
const SPECS = ['import-to-lesson', 'quiz-and-recap', 'book-and-degrade', 'search-parity'];

const USAGE = `用法: node scripts/e2e-real.mjs [--keep] [--spec <name>] [--web-port <n>] [--api-port <n>] [--fake-port <n>]
  --keep        保留本轮目录（默认跑完删除；日志上限与旧轮清理不受影响）
  --spec <name> 只跑一条用例（文件名片段，传给 playwright 的位置过滤）
  端口默认 web=3100 api=8100 fake=9911，可用 E2E_WEB_PORT / E2E_API_PORT / E2E_FAKE_PORT 覆盖
退出码: 0 全绿 / 1 有用例失败 / 2 环境不可用`;

const WIN = process.platform === 'win32';

// --------------------------------------------------------------------------- //
// 参数
// --------------------------------------------------------------------------- //

function parseArgs(argv) {
  const opts = {
    keep: false,
    spec: null,
    webPort: numberEnv('E2E_WEB_PORT', 3100),
    apiPort: numberEnv('E2E_API_PORT', 8100),
    fakePort: numberEnv('E2E_FAKE_PORT', 9911),
    help: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--keep') {
      opts.keep = true;
      continue;
    }
    if (arg === '--help' || arg === '-h') {
      opts.help = true;
      continue;
    }
    if (arg === '--spec' || arg === '--web-port' || arg === '--api-port' || arg === '--fake-port') {
      const value = argv[i + 1];
      if (!value || value.startsWith('--')) throw new Error(`${arg} 需要一个值`);
      i += 1;
      if (arg === '--spec') opts.spec = value;
      else if (arg === '--web-port') opts.webPort = toPort(arg, value);
      else if (arg === '--api-port') opts.apiPort = toPort(arg, value);
      else opts.fakePort = toPort(arg, value);
      continue;
    }
    throw new Error(`未知参数：${arg}`);
  }
  return opts;
}

function numberEnv(name, fallback) {
  const raw = (process.env[name] ?? '').trim();
  if (!raw) return fallback;
  return toPort(name, raw);
}

function toPort(label, value) {
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${label} 不是合法端口：${value}`);
  }
  return port;
}

// --------------------------------------------------------------------------- //
// 小工具
// --------------------------------------------------------------------------- //

/** 本地时间 `yyyyMMdd-HHmmss`：目录名必须**可按字典序排序**，否则清理会删错轮次。 */
function runStamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return (
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}` +
    `-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  );
}

function sleep(ms) {
  return new Promise((done) => setTimeout(done, ms));
}

function log(message) {
  process.stdout.write(`${message}\n`);
}

function warn(message) {
  process.stderr.write(`${message}\n`);
}

/**
 * 读文件内容；还没被创建时返回空串。
 *
 * `createWriteStream` 是**异步**建文件的：第 6 步刚 spawn 完就去读日志，
 * 读到 ENOENT 是完全正常的时序，不能让它把编排器打成"环境不可用"。
 */
function readIfExists(path) {
  try {
    return readFileSync(path, 'utf8');
  } catch {
    return '';
  }
}

/** 读文件最后 N 行（日志上限 5MB 之后这个函数仍然要在毫秒级返回）。 */
function tailLines(path, limit = TAIL_LINES) {
  const text = readIfExists(path);
  if (!text) return [`(日志还没有内容：${path})`];
  const lines = text.split(/\r?\n/).filter((line, index, all) => line !== '' || index < all.length - 1);
  return lines.slice(-limit);
}

/**
 * 单进程日志写入器。
 *
 * 三条规则（spec P2-6）：
 * 1. **每轮开跑时截断**（`flags: 'w'`）——上一轮的日志混进来，失败现场会被冲掉；
 * 2. 单文件超过 5MB → 写一行 `[truncated]` 并停止写入；
 * 3. `--keep` 不影响 1 和 2：保留目录是为了排查，不是为了攒满磁盘。
 */
class ProcessLog {
  constructor(filePath) {
    this.path = filePath;
    this.bytes = 0;
    this.truncated = false;
    this.closed = false;
    this.stream = createWriteStream(filePath, { flags: 'w' });
    // 收尾之后子进程仍可能吐最后几行：写流已 end，继续写会抛
    // ERR_STREAM_WRITE_AFTER_END 并把编排器自己搞崩（那会伪装成"用例失败"）。
    this.stream.on('error', () => {
      this.closed = true;
    });
  }

  write(chunk) {
    if (this.truncated || this.closed) return;
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8');
    this.bytes += buffer.length;
    if (this.bytes > LOG_CAP_BYTES) {
      this.truncated = true;
      this.stream.write(`\n[truncated] 单文件日志超过 ${LOG_CAP_BYTES} 字节，后续输出已丢弃\n`);
      this.stream.end();
      return;
    }
    this.stream.write(buffer);
  }

  close() {
    this.closed = true;
    if (!this.truncated) this.stream.end();
  }
}

/** 端口探测：占用即失败（不自动换端口，见文件头）。 */
function probePort(port) {
  return new Promise((done) => {
    const server = net.createServer();
    server.once('error', (err) => done({ ok: false, reason: `${err.code ?? 'ERROR'}` }));
    server.once('listening', () => server.close(() => done({ ok: true, reason: '' })));
    server.listen(port, '127.0.0.1');
  });
}

/** 带硬超时的 HTTP 探针（就绪判定用；任何异常都当成"还没好"）。 */
async function fetchOnce(url, timeoutMs = 3000) {
  try {
    const response = await fetch(url, {
      // 就绪判定要看真实的 3xx（`/` 在首启守卫下是 307 → /setup），不能被自动跟随吃掉。
      redirect: 'manual',
      cache: 'no-store',
      signal: AbortSignal.timeout(timeoutMs),
    });
    let body = null;
    const type = response.headers.get('content-type') ?? '';
    if (type.includes('json')) {
      try {
        body = await response.json();
      } catch {
        body = null;
      }
    } else {
      await response.arrayBuffer().catch(() => undefined);
    }
    return { ok: true, status: response.status, body };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

/** 轮询直到 `check()` 返回真值；超时返回 null（由调用方决定怎么报）。 */
async function pollUntil(check, { timeoutMs, intervalMs = 500 }) {
  const started = Date.now();
  for (;;) {
    const value = await check();
    if (value) return value;
    if (Date.now() - started >= timeoutMs) return null;
    await sleep(intervalMs);
  }
}

// --------------------------------------------------------------------------- //
// 进程管理
// --------------------------------------------------------------------------- //

/**
 * 起一个进程并把 stdout/stderr 落到日志文件。
 *
 * Windows 上 `npx` / `pnpm` 是 `.cmd` 垫片：Node 22 起直接 spawn `.cmd` 会抛
 * EINVAL（CVE-2024-27980 之后的加固），必须交给 shell 解析——但 shell 会让
 * 我们拿到的 pid 是 cmd.exe 的 pid，因此收尾一律走 `taskkill /T /F`（整棵子树）。
 */
function startProcess({ name, command, args, cwd, env, logDir }) {
  const filePath = join(logDir, `${name}.log`);
  const sink = new ProcessLog(filePath);
  const child = spawn(command, args, {
    cwd,
    env,
    shell: WIN,
    windowsHide: true,
    // POSIX 下自成进程组，收尾时 `process.kill(-pid)` 一次带走所有子进程。
    detached: !WIN,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout.on('data', (chunk) => sink.write(chunk));
  child.stderr.on('data', (chunk) => sink.write(chunk));
  child.on('error', (error) => sink.write(`[spawn error] ${error.message}\n`));
  return { name, child, log: sink, logPath: filePath, exitCode: null, exited: false };
}

/** 收整棵进程树。返回前确保 `exitCode` 已被置上或超时放弃。 */
async function stopProcess(proc) {
  proc.log.close();
  if (!proc.child || proc.exited) return;
  const pid = proc.child.pid;
  if (!pid) return;
  if (WIN) {
    spawnSync('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
  } else {
    try {
      process.kill(-pid, 'SIGKILL');
    } catch {
      try {
        proc.child.kill('SIGKILL');
      } catch {
        /* 已经死了 */
      }
    }
  }
  await pollUntil(() => proc.exited, { timeoutMs: 5000, intervalMs: 100 });
}

/** 从 `var/e2e/*` 里保留最近 `KEEP_RUNS` 轮（含刚创建的这一轮），其余删掉。 */
function pruneOldRuns(currentRunId) {
  let entries;
  try {
    entries = readdirSync(E2E_ROOT, { withFileTypes: true });
  } catch {
    return { removed: [], kept: [] };
  }
  const dirs = entries
    .filter((entry) => entry.isDirectory() && /^\d{8}-\d{6}$/.test(entry.name))
    .map((entry) => entry.name)
    .sort()
    .reverse();
  const keep = new Set(dirs.slice(0, KEEP_RUNS));
  keep.add(currentRunId);
  const removed = [];
  for (const name of dirs) {
    if (keep.has(name)) continue;
    try {
      rmSync(join(E2E_ROOT, name), { recursive: true, force: true });
      removed.push(name);
    } catch (error) {
      warn(`无法删除旧轮目录 ${name}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  return { removed, kept: [...keep].sort() };
}

// --------------------------------------------------------------------------- //
// 八步
// --------------------------------------------------------------------------- //

function resolvePython() {
  const candidate = WIN ? join(REPO_ROOT, '.venv', 'Scripts', 'python.exe') : join(REPO_ROOT, '.venv', 'bin', 'python');
  return existsSync(candidate) ? candidate : null;
}

/** 第 2 步：端口占用探测。 */
async function step2Ports(ports) {
  const taken = [];
  for (const [name, port] of Object.entries(ports)) {
    const result = await probePort(port);
    if (!result.ok) taken.push(`${name}=${port}（${result.reason}）`);
  }
  if (taken.length > 0) {
    throw new EnvError(
      `第 2 步：端口已被占用 → ${taken.join(', ')}\n` +
        '  请先运行 ` .\\stop.ps1` 清干净，然后重跑。\n' +
        '  （脚本**不会**自动换端口：换了之后"为什么这次跑在 3101"会变成新的谜，' +
        '而两个并发跑的 E2E 会互相污染数据目录却仍然全绿。）',
    );
  }
}

/** 第 3 步：隔离目录。 */
function step3Dirs(runId) {
  const runDir = join(E2E_ROOT, runId);
  const dirs = {
    runDir,
    dbFile: join(runDir, 'db.sqlite'),
    checkpointDb: join(runDir, 'langgraph.sqlite'),
    objectRoot: join(runDir, 'objects'),
    logDir: join(runDir, 'logs'),
    // v2 补（评审 P1-5）：Gate 0 结论与 pid/port 文件随本轮隔离，绝不读写开发机的 `.run/`
    stateDir: join(runDir, 'run'),
  };
  for (const path of [dirs.objectRoot, dirs.logDir, dirs.stateDir]) {
    mkdirSync(path, { recursive: true });
  }
  return dirs;
}

/** 第 4 步：显式 11 个环境变量。 */
function step4Env(dirs, ports) {
  const random = () => randomBytes(24).toString('base64url');
  return {
    ...process.env,
    // 不继承开发机 `.env` 的业务值：下面 11 个键在 pydantic-settings 里优先级高于
    // `.env`（env vars > dotenv file），因此这一轮跑的一定是本轮的库与端点。
    REPOLEARN_ENV: 'test',
    REPOLEARN_DATABASE_URL: `sqlite+aiosqlite:///${dirs.dbFile.replace(/\\/g, '/')}`,
    REPOLEARN_CHECKPOINT_DB: dirs.checkpointDb,
    REPOLEARN_OBJECT_ROOT: dirs.objectRoot,
    REPOLEARN_SECRET_KEY: random(),
    REPOLEARN_INTERNAL_TOKEN: random(),
    // 关键：template 让整条生成链路在**没有 LLM Key** 的机器上可跑，
    // 因此这条 E2E 在任何 CI / 任何新克隆上都能跑，而不是永远 skip。
    REPOLEARN_AGENT_RUNTIME: 'template',
    REPOLEARN_GITHUB_API_BASE: `http://127.0.0.1:${ports.fake}`,
    REPOLEARN_GITHUB_WEB_BASE: `http://127.0.0.1:${ports.fake}`,
    REPOLEARN_RUN_DIR: dirs.stateDir,
    // Next 的 `distDir` 是**相对项目目录**解析的（`apps/web`），传绝对路径会被
    // 拼成 `apps/web/E:\...\.next-e2e` 然后 mkdir 失败。因此这里用相对名
    // （与 spec §3.2.3 第 4 步的 `.next-e2e` 一致；第 6 步写的 `<repo>/.next-e2e`
    // 在 Next 上跑不通）。隔离目的同样达到：与 `start.ps1` 用的 `.next` 不同名。
    REPOLEARN_NEXT_DIST_DIR: '.next-e2e',
    // 端口也要显式给：API 侧的 CORS/文档链接会读它们，留空会退回 8000。
    REPOLEARN_API_PORT: String(ports.api),
    REPOLEARN_WEB_PORT: String(ports.web),
  };
}

/** 第 4/5 步：跑一个 python 子命令（cwd=apps/api，PYTHONPATH 兜底）。 */
function runPython(python, args, env, label) {
  const fullEnv = { ...env, PYTHONPATH: [API_DIR, env.PYTHONPATH].filter(Boolean).join(WIN ? ';' : ':') };
  const result = spawnSync(python, args, {
    cwd: API_DIR,
    env: fullEnv,
    encoding: 'utf8',
    windowsHide: true,
    timeout: 180_000,
    maxBuffer: 8 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) {
    const output = `${result.stdout ?? ''}${result.stderr ?? ''}`.trim();
    throw new EnvError(
      `${label} 失败（exit ${result.status ?? 'spawn-error'}）\n` +
        `${tailString(output, 40)}\n` +
        `  工作目录：${API_DIR}；解释器：${python}`,
    );
  }
  return `${result.stdout ?? ''}${result.stderr ?? ''}`.trim();
}

function tailString(text, limit) {
  const lines = String(text ?? '').split(/\r?\n/);
  return lines.slice(-limit).join('\n');
}

/** 第 5.5 步：本轮 Gate 0 结论（必须由本轮写入，禁用开发机的 `.run/`）。 */
function step5_5Preflight(dirs, env) {
  const out = join(dirs.stateDir, 'preflight.json');
  const result = spawnSync(process.execPath, [join(REPO_ROOT, 'scripts', 'probe_gates.mjs'), '--out', out], {
    cwd: REPO_ROOT,
    env,
    encoding: 'utf8',
    windowsHide: true,
    timeout: 120_000,
  });
  if (result.error || result.status !== 0) {
    // 探测脚本自己的退出码只有"参数非法"才会非 0（见 probe_gates.mjs 文件头）。
    throw new Error(`第 5.5 步 probe_gates 失败：${tailString(`${result.stdout}${result.stderr}`, 20)}`);
  }
  if (!existsSync(out)) {
    // 不直接判死：spec §3.2.6 把这种情况定义成"gates 全 unknown → book-and-degrade
    // 在第一个断言就失败"，失败信息指向第 5.5 步没跑。让它走到用例里比在这里
    // 静默退出更能说明问题，但日志必须显式喊一声。
    warn(`⚠ 第 5.5 步没有写出 ${out}：/healthz.gates 将是全 unknown（book-and-degrade 会因此失败）`);
    return { written: false, gates: null, path: out };
  }
  try {
    const payload = JSON.parse(readFileSync(out, 'utf8'));
    return { written: true, gates: payload.gates ?? null, path: out };
  } catch (error) {
    warn(`⚠ preflight.json 解析失败：${error instanceof Error ? error.message : String(error)}`);
    return { written: true, gates: null, path: out };
  }
}

/** 第 7 步：等就绪。任一超时 → 打印该进程最近 80 行日志。 */
async function waitForReady(proc, { url, label, timeoutMs, accept }) {
  const ready = await pollUntil(
    async () => {
      if (proc.exited) return { dead: true };
      const response = await fetchOnce(url);
      if (!response.ok) return null;
      if (accept(response)) return { status: response.status, body: response.body };
      return null;
    },
    { timeoutMs, intervalMs: 400 },
  );
  if (ready && !ready.dead) return ready;
  const lines = tailLines(proc.logPath);
  throw new EnvError(
    `${label} 在 ${Math.round(timeoutMs / 1000)}s 内没有就绪（${url}）` +
      (ready?.dead ? `；进程已退出（exit ${proc.exitCode}）` : '') +
      `\n----- ${proc.name}.log 最近 ${TAIL_LINES} 行 -----\n${lines.join('\n')}\n----- 结束 -----`,
  );
}

// --------------------------------------------------------------------------- //
// 退出码 2 的分类
// --------------------------------------------------------------------------- //

/** 环境不可用（≠ 产品坏了）。任何 throw EnvError 都会映射成退出码 2。 */
class EnvError extends Error {}

// --------------------------------------------------------------------------- //
// main
// --------------------------------------------------------------------------- //

async function main(argv) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (error) {
    warn(`${error instanceof Error ? error.message : String(error)}\n${USAGE}`);
    return 2;
  }
  if (opts.help) {
    log(USAGE);
    return 0;
  }

  const startedAt = Date.now();
  const ports = { web: opts.webPort, api: opts.apiPort, fake: opts.fakePort };
  const runId = runStamp();
  const procs = [];
  let dirs = null;
  let exitCode = 2;
  let preflight = null;
  let pwStats = { passed: 0, failed: 0, flaky: 0, skipped: 0 };

  try {
    // ---- 第 1 步：参数（已在上面完成）-------------------------------------
    log(`▶ 第 1 步 参数：web=${ports.web} api=${ports.api} fake=${ports.fake} spec=${opts.spec ?? '(全部)'} keep=${opts.keep}`);

    // ---- 第 2 步：端口占用（占用即失败，退出码 2）-------------------------
    await step2Ports(ports);
    log('▶ 第 2 步 端口探测：三个端口都空闲');

    // ---- 第 3 步：隔离目录 -----------------------------------------------
    mkdirSync(E2E_ROOT, { recursive: true });
    dirs = step3Dirs(runId);
    const pruned = pruneOldRuns(runId);
    log(
      `▶ 第 3 步 隔离目录：${dirs.runDir}` +
        (pruned.removed.length > 0 ? `（清理旧轮：${pruned.removed.join(', ')}）` : ''),
    );

    // ---- 第 4 步：环境变量 -----------------------------------------------
    const env = step4Env(dirs, ports);
    const python = resolvePython();
    if (!python) {
      throw new EnvError(
        '找不到 .venv 里的 python（skill: 不要静默回退到系统 python——那会污染开发机全局包）。\n' +
          '  请先运行 ` .\\start.ps1 -SkipInstall` 建好虚拟环境，然后重跑。',
      );
    }
    log(`▶ 第 4 步 环境：11 个 REPOLEARN_* 显式注入（env=test / runtime=template），python=${python}`);

    // ---- 第 5 步：准备数据 -----------------------------------------------
    runPython(python, ['-m', 'repolearn.cli', 'migrate'], env, '第 5 步 migrate');
    runPython(python, ['-m', 'repolearn.cli', 'seed-demo'], env, '第 5 步 seed-demo');
    log('▶ 第 5 步 数据：migrate + seed-demo 完成（夹具课程只读，本层不得改动它）');

    // ---- 第 5.5 步：本轮 Gate 0 结论 -------------------------------------
    preflight = step5_5Preflight(dirs, env);
    log(
      `▶ 第 5.5 步 Gate 0：${preflight.path}` +
        (preflight.gates ? ` → ${JSON.stringify(preflight.gates)}` : ''),
    );

    // ---- 第 6 步：起三进程（顺序 fake → api → web）------------------------
    const fake = startProcess({
      name: 'fake-github',
      command: python,
      args: [
        join('scripts', 'fake_github.py'),
        '--port',
        String(ports.fake),
        '--fixture',
        join('tests', 'fixtures', 'github'),
        '--snapshot',
        join('tests', 'fixtures', 'repos', 'tiny_v1'),
      ],
      cwd: REPO_ROOT,
      env,
      logDir: dirs.logDir,
    });
    procs.push(fake);
    fake.child.on('exit', (code) => {
      fake.exited = true;
      fake.exitCode = code;
    });

    const api = startProcess({
      name: 'api',
      command: python,
      args: ['-m', 'uvicorn', 'repolearn.main:app', '--host', '127.0.0.1', '--port', String(ports.api)],
      cwd: API_DIR,
      env: { ...env, PYTHONPATH: [API_DIR, env.PYTHONPATH].filter(Boolean).join(WIN ? ';' : ':') },
      logDir: dirs.logDir,
    });
    procs.push(api);
    api.child.on('exit', (code) => {
      api.exited = true;
      api.exitCode = code;
    });

    const web = startProcess({
      name: 'web',
      command: 'npx',
      args: ['next', 'dev', '--port', String(ports.web)],
      cwd: WEB_DIR,
      env: {
        ...env,
        // 平台件 D14 的坑：机器全局 NODE_ENV=production 会让 edge middleware 直接 500。
        NODE_ENV: 'development',
        REPOLEARN_API_BASE: `http://127.0.0.1:${ports.api}`,
        REPOLEARN_INTERNAL_TOKEN: env.REPOLEARN_INTERNAL_TOKEN,
        // 与第 4 步同值：相对项目目录，落到 apps/web/.next-e2e（= 与 start.ps1 的 `.next` 分开）。
        REPOLEARN_NEXT_DIST_DIR: env.REPOLEARN_NEXT_DIST_DIR,
      },
      logDir: dirs.logDir,
    });
    procs.push(web);
    web.child.on('exit', (code) => {
      web.exited = true;
      web.exitCode = code;
    });
    log('▶ 第 6 步 三进程已启动：fake-github → api → web');

    // ---- 第 7 步：等就绪 -------------------------------------------------
    // 假端点：stdout 的就绪行 + /healthz 双条件（只认一条会在慢机器上假就绪）。
    const fakeLine = await pollUntil(
      () => readIfExists(fake.logPath).includes('fake-github listening on'),
      { timeoutMs: 30_000, intervalMs: 200 },
    );
    if (!fakeLine) {
      throw new EnvError(
        `fake-github 30s 内没有打印就绪行\n----- fake-github.log 最近 ${TAIL_LINES} 行 -----\n` +
          `${tailLines(fake.logPath).join('\n')}\n----- 结束 -----`,
      );
    }
    await waitForReady(fake, {
      url: `http://127.0.0.1:${ports.fake}/healthz`,
      label: 'fake-github /healthz',
      timeoutMs: 30_000,
      accept: (response) => response.status === 200,
    });

    const apiReady = await waitForReady(api, {
      url: `http://127.0.0.1:${ports.api}/healthz`,
      label: 'api /healthz.ok',
      timeoutMs: 90_000,
      // kernel 允许 false（本轮不依赖 Agent 内核），db/migration 必须是真值。
      accept: (response) => response.status === 200 && response.body?.ok === true,
    });

    const webReady = await waitForReady(web, {
      url: `http://127.0.0.1:${ports.web}/`,
      label: 'web GET /',
      timeoutMs: 120_000,
      accept: (response) => response.status === 200 || (response.status >= 300 && response.status < 400),
    });
    log(
      `▶ 第 7 步 就绪：fake /healthz 200 · api ok=${apiReady.body?.ok} ` +
        `gates=${JSON.stringify(apiReady.body?.gates ?? {})} · web ${webReady.status}`,
    );

    // ---- 第 8 步：跑用例 -------------------------------------------------
    const jsonReport = join(dirs.logDir, 'playwright.json');
    const pwArgs = [
      'playwright',
      'test',
      '--config',
      'playwright.real.config.ts',
      // list 给人看，json 给 last-run.json 数数（两者都要，不能只留机器格式）。
      '--reporter',
      'list,json',
    ];
    if (opts.spec) pwArgs.push(opts.spec);
    const pw = startProcess({
      name: 'playwright',
      command: 'npx',
      args: pwArgs,
      cwd: WEB_DIR,
      env: {
        ...env,
        E2E_WEB_URL: `http://127.0.0.1:${ports.web}`,
        E2E_FAKE_GH_URL: `http://127.0.0.1:${ports.fake}`,
        E2E_API_URL: `http://127.0.0.1:${ports.api}`,
        PLAYWRIGHT_JSON_OUTPUT_NAME: jsonReport,
      },
      logDir: dirs.logDir,
    });
    const pwExit = await new Promise((done) => {
      pw.child.on('exit', (code, signal) => {
        pw.exited = true;
        pw.exitCode = code;
        pw.log.close();
        done(code ?? (signal ? 1 : 0));
      });
      pw.child.on('error', () => done(1));
    });
    log(`▶ 第 8 步 playwright 退出码 ${pwExit}（日志：${pw.logPath}）`);

    pwStats = readPlaywrightStats(jsonReport);
    // 有用例失败 → 1；否则 0。playwright 的非 0 也可能是"没有匹配的用例"，
    // 那属于跑错命令（不是产品失败），但同样不该给绿灯。
    exitCode = pwExit === 0 ? 0 : 1;
  } catch (error) {
    if (error instanceof EnvError) {
      exitCode = 2;
    } else {
      // 未预期异常优先按"环境不可用"处理：编排器自己崩了不该冒充"用例失败"。
      exitCode = 2;
    }
    warn(`\n✖ ${error instanceof Error ? error.message : String(error)}\n`);
    if (exitCode === 2) {
      warn('环境不可用（退出码 2）。若端口被占，请先运行 ` .\\stop.ps1`；若缺 venv，请运行 ` .\\start.ps1 -SkipInstall`。');
    }
  } finally {
    // 收整棵进程树：web → api → fake（与启动顺序相反）。
    // **失败即保留**：CI 的 `if: failure()` 要上传 `var/e2e/**/logs`，会话结束后
    // 编排器如果是唯一销毁现场的人，artifact 永远为空——最需要日志的时候日志没了。
    const keepRunDir = opts.keep || exitCode !== 0;
    for (const proc of [...procs].reverse()) {
      await stopProcess(proc);
    }
    const durationMs = Date.now() - startedAt;
    if (dirs) {
      const lastRun = {
        runId,
        ports,
        specs: opts.spec ? [opts.spec] : [...SPECS],
        passed: pwStats.passed,
        failed: pwStats.failed,
        durationMs,
        exitCode,
      };
      try {
        writeFileSync(join(E2E_ROOT, 'last-run.json'), `${JSON.stringify(lastRun, null, 2)}\n`, 'utf8');
      } catch (error) {
        warn(`无法写 last-run.json：${error instanceof Error ? error.message : String(error)}`);
      }
      log(
        `\n汇总：passed=${pwStats.passed} failed=${pwStats.failed} flaky=${pwStats.flaky} ` +
          `skipped=${pwStats.skipped} durationMs=${durationMs} exitCode=${exitCode}`,
      );
      log(`目录：${dirs.runDir}${keepRunDir ? '（已保留）' : ''}`);
      if (!keepRunDir) {
        try {
          rmSync(dirs.runDir, { recursive: true, force: true });
        } catch (error) {
          warn(`无法删除本轮目录：${error instanceof Error ? error.message : String(error)}`);
        }
      }
    }
  }
  return exitCode;
}

/** Playwright 的 json reporter → {passed, failed, flaky, skipped}。 */
function readPlaywrightStats(path) {
  try {
    const payload = JSON.parse(readFileSync(path, 'utf8'));
    const stats = payload.stats ?? {};
    return {
      passed: Number(stats.expected ?? 0),
      failed: Number(stats.unexpected ?? 0),
      flaky: Number(stats.flaky ?? 0),
      skipped: Number(stats.skipped ?? 0),
    };
  } catch {
    // 报告没写出来（例如 playwright 起不来）：数不出来就老实写 0，
    // 但退出码仍然由子进程给出，不会被这里的 0 掩盖。
    return { passed: 0, failed: 0, flaky: 0, skipped: 0 };
  }
}

process.exitCode = await main(process.argv.slice(2));
