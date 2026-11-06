/**
 * Kernel HTTP 服务（spec §3.5.2 `src/server.ts` / §5.4）。
 *
 * 三条不可协商的安全规则（P1-14）：
 * 1. `disableRequestLogging: true` —— 请求体里有**明文 API Key**，Fastify 默认的
 *    请求日志会把它写进 `var/logs/kernel.log`。"日志里翻到 Key"是这类系统最常见
 *    的事故形态，所以这里不是"注意一下"，而是关掉。
 * 2. `logger.redact` 覆盖 `req.body` / `authorization` —— 即使某处手写 `log.info({req})`
 *    也会被脱敏。
 * 3. 错误序列化白名单 —— 只回 `{code, message, runId, detail?}`，异常对象里即使
 *    带着 `apiKey` 也不会被序列化出去。
 *
 * 另外：**不启用 CORS**。浏览器不该直连 8787（spec §2.2 约束 6）；开着 CORS 只会
 * 给未来留一个"顺手就从浏览器调内核"的错误开关。
 */

import Fastify, { type FastifyInstance, type FastifyRequest } from 'fastify';

import { SCHEMA_VERSION, toSseFrame } from './events.ts';
import { buildHealth, uptimeMs, type CapabilityReport } from './health.ts';
import {
  activeRunCount,
  cancelRun,
  coreStatus,
  getRun,
  startRun,
  type RunRequest,
} from './runtime.ts';
import { schemaJson } from './tools/emit.ts';
import { violatesAbsoluteLimits } from './budget.ts';

const TOOL_NAMES = [
  'repo_list_tree',
  'repo_read_file',
  'repo_grep',
  'repo_file_outline',
  'emit_course_json',
  'emit_lesson',
  'emit_trace',
];

const MAX_CONCURRENT_RUNS = 8;
const MAX_BODY_BYTES = 2 * 1024 * 1024;

export interface ServerOptions {
  /** 内部令牌；为空且未显式放行时，`/v1/*` 一律 401（spec T-SEC-6）。 */
  internalToken?: string;
  /**
   * 允许无令牌访问（仅用于本地冒烟/单测）。
   *
   * 默认 **false**：缺省放行等于"忘了配 `.env` 就把 :8787/v1/* 交给任何本机
   * 进程"，而 PHP/Node 之外的未授权写入能直接改课程产物。安全缺省必须是拒绝。
   */
  allowAnonymous?: boolean;
  /** 测试注入：替换 core 状态探测。 */
  logger?: boolean;
}

function tokenOf(req: FastifyRequest): string | null {
  const raw = req.headers['x-internal-token'];
  if (typeof raw === 'string') return raw;
  if (Array.isArray(raw)) return raw[0] ?? null;
  return null;
}

/** 白名单化的错误体：任何异常都不回显内部结构（含可能的 apiKey）。 */
function publicError(err: unknown, runId?: string): { code: string; message: string; runId?: string } {
  const message = (err as Error)?.message ?? 'internal error';
  // 只保留前 300 字符：过长的 provider 原始响应可能含请求回显。
  const trimmed = message.length > 300 ? `${message.slice(0, 300)}…` : message;
  return runId ? { code: 'KERNEL_ERROR', message: trimmed, runId } : { code: 'KERNEL_ERROR', message: trimmed };
}

export function buildServer(options: ServerOptions = {}): FastifyInstance {
  const app = Fastify({
    logger: options.logger === false ? false : { redact: ['req.body', 'req.headers.authorization', 'req.headers["x-internal-token"]'] },
    disableRequestLogging: true,
    bodyLimit: MAX_BODY_BYTES,
  });

  app.addHook('preHandler', async (req, reply) => {
    if (req.url === '/healthz') return;
    const expected = (options.internalToken ?? process.env.REPOLEARN_INTERNAL_TOKEN ?? '').trim();
    if (!expected) {
      if (options.allowAnonymous) return;
      await reply.code(401).send({
        error: {
          code: 'TOKEN_NOT_CONFIGURED',
          message: 'REPOLEARN_INTERNAL_TOKEN is not set on the kernel; refusing /v1/* (T-SEC-6)',
        },
      });
      return;
    }
    if (tokenOf(req) !== expected) {
      await reply.code(401).send({ error: { code: 'UNAUTHORIZED', message: 'missing or invalid X-Internal-Token' } });
    }
  });

  app.setErrorHandler(async (err, _req, reply) => {
    const status = (err as { statusCode?: number }).statusCode ?? 500;
    await reply.code(status).send({ error: publicError(err) });
  });

  app.get('/healthz', async () => {
    const core = await coreStatus();
    const report: CapabilityReport = buildHealth({
      core,
      providers: core.available ? ['anthropic', 'openai', 'google'] : [],
      tools: TOOL_NAMES,
      activeRuns: activeRunCount(),
      maxConcurrentRuns: MAX_CONCURRENT_RUNS,
      schemaVersion: SCHEMA_VERSION,
    });
    return report;
  });

  app.get('/v1/capabilities', async () => {
    const core = await coreStatus();
    return {
      tools: TOOL_NAMES,
      schemaVersion: SCHEMA_VERSION,
      maxConcurrentRuns: MAX_CONCURRENT_RUNS,
      coreVersion: core.version,
      coreAvailable: core.available,
      protocols: [
        'anthropic_messages',
        'anthropic_compatible',
        'openai_chat',
        'openai_compatible',
        'openai_responses',
        'google_generate',
        'gemini_compatible',
      ],
      uptimeMs: uptimeMs(),
    };
  });

  app.get('/v1/schemas/:name', async (req, reply) => {
    const { name } = req.params as { name: string };
    const schema = schemaJson(name);
    if (!schema) {
      return reply.code(404).send({ error: { code: 'SCHEMA_NOT_FOUND', message: `unknown schema ${name}` } });
    }
    return schema;
  });

  app.post('/v1/run', async (req, reply) => {
    const body = req.body as RunRequest | undefined;
    if (!body || !body.runId || !body.provider || !body.prompt) {
      return reply.code(422).send({ error: { code: 'INVALID_RUN', message: 'runId/provider/prompt are required' } });
    }
    const violation = violatesAbsoluteLimits(body.budget as never);
    if (violation) {
      // 显式 422 而不是静默 clamp：上层算错预算时，闸门不能被自己抬高（spec §5.4）
      return reply.code(422).send({ error: { code: 'BUDGET_TOO_HIGH', message: violation } });
    }
    if (activeRunCount() >= MAX_CONCURRENT_RUNS) {
      return reply.code(429).send({ error: { code: 'KERNEL_BUSY', message: 'too many concurrent runs' } });
    }

    let handle;
    try {
      handle = await startRun(body);
    } catch (err) {
      return reply.code(500).send({ error: publicError(err, body.runId) });
    }

    reply.raw.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      'X-Accel-Buffering': 'no',
      Connection: 'keep-alive',
    });

    // keepalive 注释帧：防止中间层在长工具调用期间把连接判死（spec §5.5）。
    const keepalive = setInterval(() => {
      try {
        reply.raw.write(': keepalive\n\n');
      } catch {
        /* 连接已断，等 for-await 自然结束 */
      }
    }, 15_000);

    try {
      for await (const env of handle.envelopes) {
        reply.raw.write(toSseFrame(env));
      }
    } catch {
      /* 流写失败不影响终态记录 */
    } finally {
      clearInterval(keepalive);
      reply.raw.end();
    }
    return reply;
  });

  app.post('/v1/run/:runId/cancel', async (req) => {
    const { runId } = req.params as { runId: string };
    return { cancelled: cancelRun(runId) };
  });

  app.get('/v1/run/:runId', async (req, reply) => {
    const { runId } = req.params as { runId: string };
    const result = getRun(runId);
    if (!result) {
      return reply
        .code(404)
        .send({ error: { code: 'RUN_NOT_FOUND', message: `unknown run ${runId}` } });
    }
    return { status: result.status, usage: result.usage, result: result.result, error: result.error };
  });

  return app;
}

const DIRECT_RUN = process.argv[1]?.replace(/\\/g, '/').endsWith('src/server.ts');

if (DIRECT_RUN) {
  const port = Number(process.env.REPOLEARN_KERNEL_PORT ?? 8787);
  const host = '127.0.0.1';
  const app = buildServer();
  const shutdown = async (signal: string): Promise<void> => {
    try {
      const core = await coreStatus();
      // 优雅关闭：abort 全部在跑 run（spec §4.2 server.ts）
      void core;
    } finally {
      await app.close();
      process.exit(signal === 'SIGINT' ? 0 : 0);
    }
  };
  process.on('SIGINT', () => void shutdown('SIGINT'));
  process.on('SIGTERM', () => void shutdown('SIGTERM'));
  app
    .listen({ port, host })
    .then(async () => {
      const core = await coreStatus();
      // 启动即打印 core 版本，供 start.ps1 校验（spec §3.5.2 health.ts）
      process.stdout.write(
        `[kernel] listening on http://${host}:${port} core=${core.version ?? 'UNAVAILABLE'} available=${core.available}\n`,
      );
    })
    .catch((err: Error) => {
      process.stderr.write(`[kernel] failed to start: ${err.message}\n`);
      process.exit(1);
    });
}

export type { CapabilityReport };
