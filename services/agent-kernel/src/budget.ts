/**
 * 预算守卫（spec §3.4 Run 级 / §5.4）。
 *
 * 为什么预算必须在 Kernel 内部也有一层：Python 侧的节点级预算是"事前下发"，
 * 但它无法阻止一次调用把下发的额度全部烧光后继续（多轮工具循环）。Kernel 是
 * 唯一看得到 turns / tokens / usd 实时累加的地方，所以它必须有**主动 abort**
 * 的能力，并把 `budget_exceeded` 作为结构化事件回传，让 Python 侧决定重试还是降级。
 *
 * 三个闸门（先到的生效）：
 *   turns     —— 防止"工具循环不收敛"；
 *   tokens    —— 防止一次超长 prompt 打穿账单；
 *   deadline  —— 防止挂住的 provider 让整条 run 永远不结束。
 */

export interface BudgetLimits {
  maxTurns: number;
  maxTokens: number;
  maxUsd: number;
  deadlineMs: number;
}

export type BudgetKind = 'turns' | 'tokens' | 'usd' | 'deadline';

export class BudgetExceeded extends Error {
  readonly kind: BudgetKind;
  readonly used: number;
  readonly limit: number;
  constructor(kind: BudgetKind, used: number, limit: number) {
    super(`budget exceeded: ${kind} used=${used} limit=${limit}`);
    this.name = 'BudgetExceeded';
    this.kind = kind;
    this.used = used;
    this.limit = limit;
  }
}

export interface UsageSnapshot {
  turns: number;
  tokensIn: number;
  tokensOut: number;
  tokens: number;
  usd: number;
  elapsedMs: number;
  usageSource: 'reported' | 'estimated' | 'mixed';
}

const CHARS_PER_TOKEN = 4;

/**
 * 估算 prompt token。口径与 core 的 `estimatePromptTokens` 一致（4 字符/token），
 * 这样"没有 usage 回报"时两侧算出来的数不会互相打架（spec §3.4）。
 */
export function estimateTokens(text: string): number {
  return Math.ceil((text ?? '').length / CHARS_PER_TOKEN);
}

/** 单价（USD / 1M token）。没有价格的模型记 0 并在 warnings 里带 PRICE_UNKNOWN。 */
export interface Price {
  input: number;
  output: number;
}

export class Budget {
  readonly limits: BudgetLimits;
  private turns = 0;
  private tokensIn = 0;
  private tokensOut = 0;
  private usd = 0;
  private price: Price | null;
  private readonly startedAt: number;
  private readonly clock: () => number;
  private estimatedOnly = false;
  private reported = false;
  /** 一旦超限就**永久**锁死：允许"超了之后继续跑"等于没有闸门。 */
  private tripped: BudgetExceeded | null = null;

  constructor(limits: BudgetLimits, price: Price | null = null, clock: () => number = Date.now) {
    this.limits = limits;
    this.price = price;
    this.clock = clock;
    this.startedAt = clock();
  }

  get usage(): UsageSnapshot {
    let source: UsageSnapshot['usageSource'] = 'reported';
    if (this.estimatedOnly && this.reported) source = 'mixed';
    else if (this.estimatedOnly) source = 'estimated';
    return {
      turns: this.turns,
      tokensIn: this.tokensIn,
      tokensOut: this.tokensOut,
      tokens: this.tokensIn + this.tokensOut,
      usd: Math.round(this.usd * 1e6) / 1e6,
      elapsedMs: this.clock() - this.startedAt,
      usageSource: source,
    };
  }

  get priceKnown(): boolean {
    return this.price !== null;
  }

  beginTurn(): void {
    this.turns += 1;
    this.checkTurns();
    this.checkDeadline();
  }

  /**
   * 记录一次 LLM 用量。
   *
   * `reported=false` 表示 provider 没回 usage，此时按 `promptChars/4` 估并标记
   * `usageSource="estimated"`。**不是**"没回报就不计"——那会让成本门禁变成假数据。
   */
  record(promptChars: number, usage?: { inputTokens?: number; outputTokens?: number } | null): void {
    if (usage && (usage.inputTokens || usage.outputTokens)) {
      this.tokensIn += usage.inputTokens ?? 0;
      this.tokensOut += usage.outputTokens ?? 0;
      this.reported = true;
    } else {
      this.estimatedOnly = true;
      this.tokensIn += estimateTokens('x'.repeat(Math.max(0, promptChars)));
    }
    // 用赋值而不是累加：`computeUsd()` 是**由累计 tokens 重算总价**，累加会让
    // 第 2 轮把第 1 轮的价格再加一遍（两轮各 5000 token 会记成 3 倍价钱），
    // `maxUsd` 闸门于是远早于真实成本触发。
    this.usd = this.computeUsd();
    this.checkTokens();
    this.checkUsd();
    this.checkDeadline();
  }

  /** 记录输出侧 token（文本增量累加；没有 usage 时的唯一来源）。 */
  recordOutputTokens(tokens: number): void {
    if (tokens <= 0) return;
    this.estimatedOnly = true;
    this.tokensOut += tokens;
    this.usd = this.computeUsd();
    this.checkTokens();
    this.checkUsd();
  }

  /** 在每个可能"跑很久"的检查点调用；超限即抛。 */
  tick(): void {
    if (this.tripped) throw this.tripped;
    this.checkDeadline();
  }

  private computeUsd(): number {
    if (!this.price) return 0;
    return (this.tokensIn / 1_000_000) * this.price.input + (this.tokensOut / 1_000_000) * this.price.output;
  }

  private checkTurns(): void {
    if (this.turns > this.limits.maxTurns) this.fail(new BudgetExceeded('turns', this.turns, this.limits.maxTurns));
  }
  private checkTokens(): void {
    const used = this.tokensIn + this.tokensOut;
    if (used > this.limits.maxTokens) this.fail(new BudgetExceeded('tokens', used, this.limits.maxTokens));
  }
  private checkUsd(): void {
    if (this.limits.maxUsd > 0 && this.usd > this.limits.maxUsd) {
      this.fail(new BudgetExceeded('usd', this.usd, this.limits.maxUsd));
    }
  }
  private checkDeadline(): void {
    const elapsed = this.clock() - this.startedAt;
    if (elapsed > this.limits.deadlineMs) {
      this.fail(new BudgetExceeded('deadline', elapsed, this.limits.deadlineMs));
    }
  }
  private fail(e: BudgetExceeded): never {
    this.tripped = e;
    throw e;
  }
}

/**
 * 请求体里下发值的硬上限（spec §5.4）。
 *
 * "Kernel 只接受不高于 Python 侧下发值的上限"这句话如果只写在文档里就是空话；
 * 这里把它变成 422：上层算错预算时，闸门不能被自己抬高。
 */
export const ABSOLUTE_LIMITS = {
  maxTurns: 64,
  maxTokens: 200_000,
  maxUsd: 10,
  deadlineMs: 900_000,
} as const;

export function clampLimits(input: Partial<BudgetLimits> | undefined): BudgetLimits {
  const l = input ?? {};
  const num = (v: unknown, fallback: number): number =>
    typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : fallback;
  return {
    maxTurns: Math.min(num(l.maxTurns, 16), ABSOLUTE_LIMITS.maxTurns),
    maxTokens: Math.min(num(l.maxTokens, 12_000), ABSOLUTE_LIMITS.maxTokens),
    maxUsd: Math.min(num(l.maxUsd, 1), ABSOLUTE_LIMITS.maxUsd),
    deadlineMs: Math.min(num(l.deadlineMs, 120_000), ABSOLUTE_LIMITS.deadlineMs),
  };
}

/** 上浮超限判定：请求里显式写了超过绝对上限的值 → 直接拒绝（422），不是静默 clamp。 */
export function violatesAbsoluteLimits(input: Partial<BudgetLimits> | undefined): string | null {
  if (!input) return null;
  for (const key of Object.keys(ABSOLUTE_LIMITS) as Array<keyof typeof ABSOLUTE_LIMITS>) {
    const v = input[key];
    if (typeof v === 'number' && v > ABSOLUTE_LIMITS[key]) {
      return `${key}=${v} exceeds kernel ceiling ${ABSOLUTE_LIMITS[key]}`;
    }
  }
  return null;
}
