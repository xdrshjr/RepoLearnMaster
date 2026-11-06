/**
 * Kernel 运行时（spec §3.5.2 `src/runtime.ts`）。
 *
 * 这个文件是"Python 的 AgentRuntime 协议"在 Node 侧的另一半，它只做四件事：
 *
 * 1. **把 `@aragon-agent/core` 当作可选依赖加载**。包是闭源的、从私有 registry 发布，
 *    因此"装不上"必须是**可表达的状态**而不是进程启动失败（spec §3.5.3 状态 C）。
 * 这里用动态 import 并缓存结果，`/healthz` 据此报告 `degraded`。
 * 2. **一次性 run 的生命周期表**。cancel 需要在 run 之外被调用，所以必须有
 *    `runId → {abort, finished}` 的映射；run 结束时立刻删除，避免长跑进程里
 *    越积越多（这是最容易泄漏的地方）。
 * 3. **把 API Key 关在单次 run 的闭包里**（spec §5.4 硬规则③）。`getApiKey` 是
 *    core 的注入点，闭包在 `finally` 里被置空——Kernel 不缓存、不落盘、不写临时文件。
 * 4. **预算主动 abort**。core 不认我们的预算，所以由订阅者计量并在超限时调
 *    `agent.abort()`，把"超支"变成一条 `budget.exceeded` 事件而不是一次静默的巨额账单。
 */

import { createEmitSlot, createEmitTools, type EmitSlot } from './tools/emit.ts';
import { createRepoTools } from './tools/repo.ts';
import { Budget, BudgetExceeded, clampLimits, estimateTokens, type Price } from './budget.ts';
import { envelope, makeEnvelopeContext, mapCoreEvent, type CoreEventLike, type Envelope } from './events.ts';
import type { CoreStatus } from './health.ts';

/* -------------------------------------------------------------------------- */
/* core 的动态加载                                                             */
/* -------------------------------------------------------------------------- */

export interface CoreModule {
  Agent: new (config: Record<string, unknown>) => CoreAgent;
  defineTool: (config: Record<string, unknown>) => unknown;
  initProviders: (options?: Record<string, unknown>) => CoreRegistry;
}

export interface CoreAgent {
  prompt(message: string): Promise<void>;
  abort(): void;
  subscribe(listener: (event: Record<string, unknown>) => void): () => void;
  setMaxTokens(value: number | undefined): void;
}

export interface CoreRegistry {
  getAll(): Array<{ id?: string; name?: string }>;
  getDefaultBaseUrl(id: string): string;
}

let corePromise: Promise<CoreModule | null> | null = null;

export async function loadCore(): Promise<CoreModule | null> {
  if (!corePromise) {
    corePromise = (async () => {
      try {
        const mod = (await import('@aragon-agent/core')) as unknown as CoreModule;
        if (typeof mod.Agent !== 'function' || typeof mod.initProviders !== 'function') return null;
        return mod;
      } catch {
        return null;
      }
    })();
  }
  return corePromise;
}

export function resetCoreCache(): void {
  corePromise = null;
}

export async function coreStatus(): Promise<CoreStatus> {
  const core = await loadCore();
  if (!core) {
    return { available: false, version: null, exports: [], error: 'cannot import @aragon-agent/core' };
  }
  let version: string | null = null;
  // BEST-EFFORT only: a missing version must never turn "available" into
  // "unavailable". `require('@aragon-agent/core/package.json')` throws
  // ERR_PACKAGE_PATH_NOT_EXPORTED (the exports map hides package.json), so we
  // locate the package directory on disk instead -- same three traps as
  // scripts/probe_core.mjs.
  try {
    const { existsSync, readFileSync } = await import('node:fs');
    const { dirname, join, resolve } = await import('node:path');
    let dir = resolve(process.cwd());
    for (let i = 0; i < 12; i += 1) {
      const candidate = join(dir, 'node_modules', '@aragon-agent', 'core', 'package.json');
      if (existsSync(candidate)) {
        const parsed = JSON.parse(readFileSync(candidate, 'utf8')) as { version?: string };
        version = parsed.version ?? null;
        break;
      }
      const parent = dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  } catch {
    version = null;
  }
  return {
    available: true,
    version,
    exports: Object.keys(core as unknown as Record<string, unknown>).slice(0, 40),
    error: null,
  };
}

/* -------------------------------------------------------------------------- */
/* 请求/响应形状                                                              */
/* -------------------------------------------------------------------------- */

export interface ProviderSpec {
  id: string;
  protocol: string;
  baseUrl?: string | null;
  apiKey: string;
  modelId: string;
  priceIn?: number | null;
  priceOut?: number | null;
}

export interface RunRequest {
  runId: string;
  role: string;
  provider: ProviderSpec;
  systemPrompt: string;
  prompt: string;
  tools?: string[];
  schemaRef?: string | null;
  budget?: Record<string, unknown>;
  workspace?: { mirrorDir?: string | null };
  metadata?: Record<string, unknown>;
}

export interface RunResult {
  status: 'completed' | 'failed' | 'cancelled' | 'budget_exceeded' | 'degraded';
  result: Record<string, unknown>;
  usage: Record<string, unknown>;
  error?: { code: string; message: string } | null;
}

interface LiveRun {
  abort: (reason: string) => void;
  finished: boolean;
  reason: string | null;
}

const live = new Map<string, LiveRun>();

export function activeRunCount(): number {
  return live.size;
}

export function cancelRun(runId: string): boolean {
  const r = live.get(runId);
  if (!r) return false;
  r.reason = 'cancelled';
  r.abort('cancelled');
  return true;
}

export function getRun(runId: string): RunResult | null {
  return lastResults.get(runId) ?? null;
}

const lastResults = new Map<string, RunResult>();

export function recordResult(runId: string, result: RunResult): void {
  lastResults.set(runId, result);
  // 只保留最近 200 条，防止长跑进程内存增长。
  if (lastResults.size > 200) {
    const oldest = lastResults.keys().next().value;
    if (oldest) lastResults.delete(oldest);
  }
}

/* -------------------------------------------------------------------------- */
/* 协议 → core provider 的映射                                                 */
/* -------------------------------------------------------------------------- */

/**
 * core 只有三个内置 provider。自定义网关通过 `baseUrl` 复用其中一个，
 * 这是行业通行做法（OpenAI 兼容网关 = openai + baseUrl）。
 *
 * `openai_responses` 在本版本按 openai chat 处理并在 metadata 里记一条警告：
 * Responses API 的工具调用形状不同，Kernel 不假装支持它（宁可降级也不静默出错）。
 */
export function mapProtocol(protocol: string): { providerId: string; note?: string } {
  switch (protocol) {
    case 'anthropic_messages':
      return { providerId: 'anthropic' };
    case 'anthropic_compatible':
      return { providerId: 'anthropic', note: 'anthropic-compatible gateway' };
    case 'openai_chat':
    case 'openai_compatible':
      return { providerId: 'openai' };
    case 'openai_responses':
      return { providerId: 'openai', note: 'openai_responses is served via chat completions in this version' };
    case 'google_generate':
    case 'gemini_compatible':
      return { providerId: 'google', note: 'gemini-compatible gateway' };
    default:
      return { providerId: 'openai', note: `unknown protocol ${protocol}, falling back to openai` };
  }
}

const DEFAULT_TOOL_NAMES = [
  'repo_list_tree',
  'repo_read_file',
  'repo_grep',
  'repo_file_outline',
  'emit_course_json',
  'emit_lesson',
  'emit_trace',
];

/**
 * 产出工具是**交付通道**，不是可选项。
 *
 * `req.tools` 表达的是"这次允许用哪些只读仓库工具"（Python 侧只下发 4 个 repo
 * 工具）。若把它的语义扩大成"完整工具白名单"，emit_* 会被过滤掉，Agent 于是
 * 只能输出自然语言，Python 侧 `_extract_text` 拿到空串、判 `CONTRACT_VIOLATION`
 * ——每一次带真实模型的生成都会失败，而症状看起来像是"模型不听话"。
 */
const EMIT_TOOL_NAMES = ['emit_course_json', 'emit_lesson', 'emit_trace'];

/**
 * `req.tools` 的语义 = "允许的只读仓库工具"；产出工具永远并入。
 *
 * 抽成纯函数是为了能被单测直接钉住：这一段一旦被改回"完整白名单"，
 * 带真实模型的生成会全体失败，而失败现象（CONTRACT_VIOLATION）看不出根因。
 */
export function resolveAllowedTools(requested?: string[] | null): string[] {
  const base = requested && requested.length > 0 ? requested : DEFAULT_TOOL_NAMES;
  const out = new Set<string>();
  for (const name of [...base, ...EMIT_TOOL_NAMES]) {
    // 只保留真实存在的工具名：白名单是"允许用哪些"，不是"声明想用哪些"。
    // 未知名字由 startRun 记进 `slot.failures`，不进工具列表。
    if (DEFAULT_TOOL_NAMES.includes(name)) out.add(name);
  }
  return [...out];
}

/* -------------------------------------------------------------------------- */
/* 主流程                                                                     */
/* -------------------------------------------------------------------------- */

export interface RunHandle {
  runId: string;
  envelopes: AsyncIterable<Envelope>;
  done: Promise<RunResult>;
}

/**
 * 启动一次 run，返回事件流与终态 promise。
 *
 * 关键设计：**事件流与终态是两个独立的消费面**。HTTP 层只负责把 envelopes 写成
 * SSE；调用方（Python）从 `run.completed` 里拿结果。二者共用同一份 `EmitSlot`，
 * 所以"流里看到的"和"最终交付的"永远是同一份数据。
 */
export async function startRun(req: RunRequest): Promise<RunHandle> {
  const core = await loadCore();
  const ctx = makeEnvelopeContext(req.runId, (req.metadata?.job_id as string | undefined) ?? null);
  const slot = createEmitSlot();
  const budget = new Budget(clampLimits(req.budget as never), priceOf(req.provider));
  const provider = mapProtocol(req.provider.protocol);

  if (!core) {
    return degradedRun(req, ctx, provider, 'core_unavailable');
  }

  let registry: CoreRegistry;
  try {
    registry = core.initProviders();
  } catch (err) {
    return degradedRun(req, ctx, provider, `initProviders failed: ${(err as Error).message}`);
  }

  const requested = new Set(req.tools && req.tools.length > 0 ? req.tools : DEFAULT_TOOL_NAMES);
  const allowed = new Set(resolveAllowedTools(req.tools));
  const repoTools = req.workspace?.mirrorDir ? createRepoTools(req.workspace.mirrorDir) : [];
  const emitTools = createEmitTools(slot);
  const toolList = [...repoTools, ...emitTools].filter((t) =>
    allowed.has((t as { name: string }).name),
  );
  for (const name of requested) {
    if (!DEFAULT_TOOL_NAMES.includes(name)) {
      slot.failures.push({ tool: 'whitelist', error: `unknown tool requested: ${name}` });
    }
  }

  // ---- 事件桥：core 的同步 listener → 异步队列 -----------------------------
  const queue: Envelope[] = [];
  const waiters: Array<() => void> = [];
  let streamClosed = false;
  const push = (env: Envelope): void => {
    queue.push(env);
    const w = waiters.shift();
    if (w) w();
  };
  const closeStream = (): void => {
    streamClosed = true;
    while (waiters.length > 0) {
      const w = waiters.shift();
      if (w) w();
    }
  };

  // API Key 只活在这个闭包里（spec §5.4 硬规则③）
  const keyBox: { value: string | null } = { value: req.provider.apiKey };

  let budgetTripped: BudgetExceeded | null = null;
  let agentRef: CoreAgent | null = null;
  let abortReason: string | null = null;

  push(
    envelope(ctx, 'system.init', {
      model: req.provider.modelId,
      provider: provider.providerId,
      protocol: req.provider.protocol,
      tools: toolList.map((t) => (t as { name: string }).name),
      role: req.role,
      priceKnown: budget.priceKnown,
      notes: provider.note ? [provider.note] : [],
    }),
  );

  let agent: CoreAgent;
  try {
    agent = new core.Agent({
      systemPrompt: req.systemPrompt,
      model: {
        providerId: provider.providerId,
        modelId: req.provider.modelId,
        ...(req.provider.baseUrl ? { baseUrl: req.provider.baseUrl } : {}),
      },
      tools: toolList,
      providerRegistry: registry,
      getApiKey: (providerId: string) => (providerId === provider.providerId ? keyBox.value ?? undefined : undefined),
      maxTokens: budget.limits.maxTokens,
      // 空闲看门狗不能比我们的 deadline 更紧，否则一个慢工具会被误判为挂死；
      // 也不能更松，否则真挂住时预算闸门要等 deadline 才生效。
      timeouts: { idleTimeout: Math.min(budget.limits.deadlineMs, 180_000), llmCallTimeout: 180_000 },
    });
    agentRef = agent;
  } catch (err) {
    keyBox.value = null;
    return degradedRun(req, ctx, provider, `Agent construction failed: ${(err as Error).message}`);
  }

  const unsubscribe = agent.subscribe((event: Record<string, unknown>) => {
    try {
      for (const env of mapCoreEvent(ctx, event as unknown as CoreEventLike)) push(env);
      const t = event.type;
      if (t === 'turn_start') {
        try {
          budget.beginTurn();
        } catch (e) {
          budgetTripped = e as BudgetExceeded;
          abortReason = 'budget';
          agent.abort();
        }
      }
      if (t === 'message_update') {
        const se = (event as { streamEvent?: { type?: string; delta?: string } }).streamEvent;
        if (se?.type === 'text_delta' && typeof se.delta === 'string') {
          // 保守估计输出侧 token：只在没有 usage 时才作为唯一来源。
          budget.recordOutputTokens(Math.ceil(se.delta.length / 4));
        }
      }
      if (t === 'turn_end') {
        const usage = (event as { usage?: { inputTokens?: number; outputTokens?: number } }).usage;
        if (usage) {
          // 上报的 usage 必须真的用上：传 0 会让 tokensIn 永远为 0，
          // token 闸门只数输出侧，长 prompt 短回答的调用会完全逃过预算核算。
          budget.record(0, {
            inputTokens: Math.max(0, usage.inputTokens ?? 0),
            outputTokens: 0, // 输出侧已由 text_delta 逐字累加，避免双计
          });
        }
      }
    } catch (e) {
      budgetTripped = e as BudgetExceeded;
      abortReason = 'budget';
      agent.abort();
    }
  });

  const live: LiveRun = {
    abort: (reason) => {
      abortReason = reason;
      try {
        agent.abort();
      } catch {
        /* abort 失败不改变终态判定 */
      }
    },
    finished: false,
    reason: null,
  };
  liveMapSet(req.runId, live);

  const done = (async (): Promise<RunResult> => {
    try {
      await agent.prompt(req.prompt);
      const usage = budget.usage;
      if (budgetTripped) {
        const exceeded = budgetTripped as BudgetExceeded;
        push(
          envelope(ctx, 'budget.exceeded', {
            kind: exceeded.kind,
            used: exceeded.used,
            limit: exceeded.limit,
          }),
        );
        const result: RunResult = {
          status: 'budget_exceeded',
          result: collect(slot),
          usage: { ...usage },
          error: { code: 'BUDGET_EXCEEDED', message: exceeded.message },
        };
        push(envelope(ctx, 'run.failed', { code: 'BUDGET_EXCEEDED', message: exceeded.message, retryable: false }));
        recordResult(req.runId, result);
        return result;
      }
      if (abortReason === 'cancelled') {
        const result: RunResult = {
          status: 'cancelled',
          result: collect(slot),
          usage: { ...usage },
          error: { code: 'CANCELLED', message: 'run cancelled' },
        };
        push(envelope(ctx, 'run.failed', { code: 'CANCELLED', message: 'run cancelled', retryable: false }));
        recordResult(req.runId, result);
        return result;
      }
      const result: RunResult = {
        status: 'completed',
        result: collect(slot),
        usage: { ...usage },
        error: null,
      };
      push(envelope(ctx, 'run.completed', { result: result.result, usage: result.usage }));
      recordResult(req.runId, result);
      return result;
    } catch (err) {
      const usage = budget.usage;
      const message = (err as Error)?.message ?? String(err);
      const code = message.includes('idle') ? 'PROVIDER_UNAVAILABLE' : 'KERNEL_RUN_FAILED';
      // abort 之后 core 有可能 reject 而不是 resolve：预算超限与用户取消必须
      // 优先判定，否则会以 `retryable:true` 把"已超预算/已取消"的 run 交回
      // Python 侧重试，等于把闸门和取消按钮一起失效。
      if (budgetTripped) {
        const exceeded = budgetTripped as BudgetExceeded;
        push(
          envelope(ctx, 'budget.exceeded', {
            kind: exceeded.kind,
            used: exceeded.used,
            limit: exceeded.limit,
          }),
        );
        const tripped: RunResult = {
          status: 'budget_exceeded',
          result: collect(slot),
          usage: { ...usage },
          error: { code: 'BUDGET_EXCEEDED', message: exceeded.message },
        };
        push(envelope(ctx, 'run.failed', { code: 'BUDGET_EXCEEDED', message: exceeded.message, retryable: false }));
        recordResult(req.runId, tripped);
        return tripped;
      }
      if (abortReason === 'cancelled') {
        const cancelled: RunResult = {
          status: 'cancelled',
          result: collect(slot),
          usage: { ...usage },
          error: { code: 'CANCELLED', message: 'run cancelled' },
        };
        push(envelope(ctx, 'run.failed', { code: 'CANCELLED', message: 'run cancelled', retryable: false }));
        recordResult(req.runId, cancelled);
        return cancelled;
      }
      const result: RunResult = {
        status: 'failed',
        result: collect(slot),
        usage: { ...usage },
        error: { code, message },
      };
      push(envelope(ctx, 'run.failed', { code, message, retryable: true }));
      recordResult(req.runId, result);
      return result;
    } finally {
      unsubscribe();
      live.finished = true;
      live.reason = abortReason;
      liveMapDelete(req.runId);
      // 密钥置空：不缓存、不写临时文件（spec §5.4 硬规则③）
      keyBox.value = null;
      if (agentRef) agentRef = null;
      closeStream();
    }
  })();

  const envelopes: AsyncIterable<Envelope> = {
    [Symbol.asyncIterator](): AsyncIterator<Envelope> {
      return {
        async next(): Promise<IteratorResult<Envelope>> {
          for (;;) {
            const item = queue.shift();
            if (item) return { value: item, done: false };
            if (streamClosed) return { value: undefined, done: true };
            await new Promise<void>((resolve) => waiters.push(resolve));
          }
        },
      };
    },
  };

  return { runId: req.runId, envelopes, done };
}

function liveMapSet(runId: string, run: LiveRun): void {
  live.set(runId, run);
}
function liveMapDelete(runId: string): void {
  live.delete(runId);
}

function priceOf(spec: ProviderSpec): Price | null {
  const input = typeof spec.priceIn === 'number' ? spec.priceIn : null;
  const output = typeof spec.priceOut === 'number' ? spec.priceOut : null;
  if (input === null || output === null) return null;
  if (input === 0 && output === 0) return null;
  return { input, output };
}

function collect(slot: EmitSlot): Record<string, unknown> {
  return {
    curriculum: slot.curriculum ?? null,
    lessons: slot.lessons,
    traces: slot.traces,
    quizzes: slot.quizzes,
    failures: slot.failures,
  };
}

/**
 * 降级 run：core 不可用时**不冒充成功**。
 *
 * 它仍然产出一条 `system.init` + 一条 `run.failed(CORE_UNAVAILABLE)`，让 Python 侧
 * 能据此走状态 C（模板降级），并在 UI 上明示"课程为简化版"（spec §3.5.3）。
 * 假装跑通、返回空结果，才是这里最坏的做法。
 */
function degradedRun(
  req: RunRequest,
  ctx: ReturnType<typeof makeEnvelopeContext>,
  provider: { providerId: string; note?: string },
  reason: string,
): RunHandle {
  const result: RunResult = {
    status: 'degraded',
    result: { curriculum: null, lessons: {}, traces: {}, quizzes: {}, failures: [] },
    usage: { turns: 0, tokens: 0, usd: 0, usageSource: 'estimated' },
    error: { code: 'CORE_UNAVAILABLE', message: reason },
  };
  const seq: Envelope[] = [
    envelope(ctx, 'system.init', { degraded: true, reason, provider: provider.providerId }),
    envelope(ctx, 'run.failed', { code: 'CORE_UNAVAILABLE', message: reason, retryable: false }),
  ];
  recordResult(req.runId, result);
  const envelopes: AsyncIterable<Envelope> = {
    [Symbol.asyncIterator](): AsyncIterator<Envelope> {
      let i = 0;
      return {
        async next(): Promise<IteratorResult<Envelope>> {
          if (i >= seq.length) return { value: undefined, done: true };
          const v = seq[i] as Envelope;
          i += 1;
          return { value: v, done: false };
        },
      };
    },
  };
  return { runId: req.runId, envelopes, done: Promise.resolve(result) };
}

export { estimateTokens };
