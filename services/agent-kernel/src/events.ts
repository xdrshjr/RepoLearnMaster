/**
 * 事件信封（spec §5.5）。
 *
 * Kernel 只产出这一种形状：`{schemaVersion, type, seq, ts, jobId, runId, data}`。
 * 为什么不让 Python 侧直接消费 core 的原始事件：core 的事件是**实现细节**
 * （`message_update` 里面再套一个 `streamEvent` 联合类型），一旦升级就可能变形；
 * 统一的信封是两侧唯一的编译期/运行期契约，未知 `type` 前端只记日志不崩
 * （spec §5.5 规则 3）。
 */

export const SCHEMA_VERSION = 1;

export type EnvelopeType =
  | 'system.init'
  | 'agent.thinking'
  | 'agent.text.delta'
  | 'tool.start'
  | 'tool.end'
  | 'run.completed'
  | 'run.failed'
  | 'budget.exceeded'
  | 'keepalive';

export interface Envelope<T = unknown> {
  schemaVersion: number;
  type: EnvelopeType;
  seq: number;
  ts: number;
  jobId: string | null;
  runId: string;
  data: T;
}

/** 单调递增的序号分配器。断线续传靠它精确对齐（spec §5.5 规则 1）。 */
export class SeqCounter {
  private value = 0;
  next(): number {
    this.value += 1;
    return this.value;
  }
  get current(): number {
    return this.value;
  }
}

export interface EnvelopeContext {
  readonly runId: string;
  readonly jobId: string | null;
  readonly seq: SeqCounter;
  readonly now: () => number;
}

export function makeEnvelopeContext(runId: string, jobId: string | null, now = Date.now): EnvelopeContext {
  return { runId, jobId, seq: new SeqCounter(), now };
}

export function envelope<T>(ctx: EnvelopeContext, type: EnvelopeType, data: T): Envelope<T> {
  return {
    schemaVersion: SCHEMA_VERSION,
    type,
    seq: ctx.seq.next(),
    ts: ctx.now(),
    jobId: ctx.jobId,
    runId: ctx.runId,
    data,
  };
}

/** SSE 帧：`id` 必须是 seq，客户端用 `Last-Event-ID` 续传。 */
export function toSseFrame(env: Envelope<unknown>): string {
  return `id: ${env.seq}\nevent: ${env.type}\ndata: ${JSON.stringify(env)}\n\n`;
}

export interface CoreEventLike {
  type: string;
  [key: string]: unknown;
}

interface StreamEventLike {
  type?: string;
  attempt?: number;
  delta?: string;
  toolName?: string;
  toolCallId?: string;
  args?: unknown;
  message?: { content?: Array<Record<string, unknown>> };
  usage?: { inputTokens?: number; outputTokens?: number };
  error?: Error;
}

/**
 * 把 core 的 `AgentEvent` 映射成信封。
 *
 * 返回 `null` 表示"这条事件对上层没有意义"——**丢弃并计数，不抛错**。
 * 这是 R1（闭源包升级导致事件形状变化）在运行期的唯一防线：Kernel 不允许
 * 因为多了一种不认识的事件就把整条 run 打断。
 */
export function mapCoreEvent(ctx: EnvelopeContext, event: CoreEventLike): Envelope<unknown>[] {
  switch (event.type) {
    case 'agent_start':
      return [];
    case 'agent_end':
      return [];
    case 'message_update': {
      const se = (event as { streamEvent?: StreamEventLike }).streamEvent;
      if (!se || typeof se.type !== 'string') return [];
      switch (se.type) {
        case 'text_delta':
          return se.delta ? [envelope(ctx, 'agent.text.delta', { delta: se.delta })] : [];
        case 'thinking_delta':
          return se.delta ? [envelope(ctx, 'agent.thinking', { text: se.delta })] : [];
        case 'tool_call_start':
          return [envelope(ctx, 'tool.start', { name: se.toolName, argsPreview: '', callId: se.toolCallId })];
        case 'retry_scheduled':
          // 重试是"暂停"语义，不是用户可见进度；但它是排错时唯一的时间线证据。
          return [envelope(ctx, 'agent.thinking', { text: `[retry] 第 ${String(se.attempt ?? '?')} 次重试` })];
        default:
          return [];
      }
    }
    case 'tool_execution_start':
      return [
        envelope(ctx, 'tool.start', {
          name: event.toolName,
          argsPreview: previewArgs(event.args),
          callId: event.toolCallId,
        }),
      ];
    case 'tool_execution_end': {
      const result = event.result as { content?: Array<{ type?: string; text?: string }> } | undefined;
      const bytesOut = typeof result?.content?.[0]?.text === 'string' ? result.content[0].text.length : 0;
      return [
        envelope(ctx, 'tool.end', {
          callId: event.toolCallId,
          ok: !event.isError,
          bytesOut,
          truncated: /"truncated"\s*:\s*true/.test(result?.content?.[0]?.text ?? ''),
        }),
      ];
    }
    case 'turn_end': {
      const usage = event.usage as { inputTokens?: number; outputTokens?: number } | undefined;
      return [
        envelope(ctx, 'agent.thinking', {
          text: '',
          usage: {
            tokensIn: usage?.inputTokens ?? 0,
            tokensOut: usage?.outputTokens ?? 0,
          },
        }),
      ];
    }
    case 'compaction_start':
      return [envelope(ctx, 'agent.thinking', { text: '[context] 上下文压缩中' })];
    case 'compaction_end':
      return [];
    default:
      return [];
  }
}

function previewArgs(args: unknown): string {
  if (args === null || args === undefined) return '';
  try {
    const s = JSON.stringify(args);
    return s.length > 240 ? `${s.slice(0, 240)}…` : s;
  } catch {
    return '';
  }
}

/** 从 `arguments` 里挑最后一个字符串值（用于 tool.start 的人类可读摘要）。 */
export function pickPrimaryArg(args: unknown): string | null {
  if (!args || typeof args !== 'object') return null;
  const obj = args as Record<string, unknown>;
  for (const key of ['file', 'path', 'pattern', 'name', 'query']) {
    const v = obj[key];
    if (typeof v === 'string' && v.length > 0) return v;
  }
  return null;
}
