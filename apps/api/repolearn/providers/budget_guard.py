"""预算守卫（spec §3.7.3 / §3.4 三级预算的 Python 侧）。

这一层与 Kernel 的 `budget.ts` 是**两个独立的闸门**，不是重复：
* Python 侧在调用前估算 prompt 规模，防止"一条超长 prompt 直接打穿预算"；
* Kernel 侧在调用中实时计量，防止"多轮工具循环不收敛"。

只有一侧是不够的：只做前者管不住循环，只做后者则超长 prompt 已经花出去钱了。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from repolearn.core.clock import monotonic_ms

CHARS_PER_TOKEN = 4

#: 每个节点允许的**工具循环轮数**（下发给 Kernel 的 `maxTurns`）。
#:
#: 这是 2026-11-09 那次 `used=213725 limit=200000` 的**真正原因**：
#: 一次 run 的 token 用量 ≈ 轮数 × 每轮上下文，而每轮上下文包含之前的全部
#: 工具结果——`repo_read_file` 单文件上限 256KB ≈ 64k tokens。于是"同一个 16 轮
#: 上限"在规划节点上能被一次文件读取放大到 20 万级。
#:
#: 规划节点**不需要**读满 16 个文件：锚点、调用链、知识图摘要已经在 prompt 里，
#: 它读文件的目的是确认两三处关键位置。把轮数按节点用途收紧，比事后抬高 token
#: 上限有效得多——抬上限只是把同一个放大器调大。
NODE_MAX_TURNS: dict[str, int] = {
    # 2026-11-09 第二次实测（sherlock@c588d7c8，真实模型）：planner 在**没有任何
    # 约束**时会连着读 8 轮（sherlock.py 分三段读完 + tests + pyproject），第 10 轮
    # 才 emit，第 11 轮还想"总结一句"时撞顶。轮数收到 6 的后果不是"省了钱"，而是
    # **每一门真实仓库的课都降级成模板版**。
    #
    # 现在的组合是"先说清楚读几个 + 给足轮数"：
    # * prompt 里写明最多读 `PLANNER_MAX_FILE_READS`(3) 个文件就交付；
    # * 轮数给 12 = 3 次读 + 1 次交付 + 1 次 schema 修正 + 富余；
    # * token 额度仍是 250k 的硬闸——真正的放大器是"每轮上下文"，那道闸在这里。
    # 两者必须一起看：只抬轮数等于给放大器换更大的桶。
    "plan_curriculum": 12,
    # 实测（sherlock@c588d7c8，2026-11-09 连续几轮真机）：
    # * 8 轮：105,736 tokens 仍未交付（模型在通读文件）；
    # * 10 轮：仍有课时 `turns used=11 limit=10` —— 它需要 11 轮才写出 emit。
    # 12 轮 = 1 次 outline/grep 核对 + 1 次交付 + 1 次 schema 修正 + 富余。
    # 交付成功即终止（Kernel 的 `onDelivered`），所以多给的轮数不会被白白烧掉。
    "write_lessons": 12,
    "simulate_trace": 4,
    "analyze_repo": 2,
    "synthesize_audio": 1,
}
DEFAULT_MAX_TURNS = 8

#: 节点级分闸（spec §3.4）。任一节点超限只让**该课时**失败，不拖垮整门课程。
#:
#: 两次实测把这两个数钉出来的：
#: * v1 `plan_curriculum=20_000` → `used=30212` 必撞（规划 prompt 本身就有 30k）；
#: * 放到 200_000 → `used=213725` 仍撞（16 轮工具循环 × 每轮 10k+ 上下文）。
#: 所以额度必须按"轮数 × 每轮上下文"来给，而不是按"一次 LLM 调用"来给。
#: 现在轮数收到 6，额度给 250k（6 轮 × 40k 的富余量），两者一起看才不会互相打架。
NODE_BUDGETS: dict[str, int] = {
    "plan_curriculum": 250_000,
    # 每个课时的 token 分闸。实测分布（sherlock，12 个课时）：
    #   中位数约 150k，长的（sherlock.py 段落）到 200k+；出现过 203k / 204k 的越界。
    # 150k → 200k → 240k 是三次真机上调的结果。240k 与 12 课时 × 3M 的 job 总闸
    # 是一对：超出的课时会被 job 级预留逐步压小，最终以 `partial` + 警告落地，
    # 而不是整门课作废。
    "write_lessons": 240_000,
    "simulate_trace": 60_000,
    "synthesize_audio": 0,
    "analyze_repo": 40_000,
}
#: 给后续课时留的余量（job 级总闸在 `JobBudget` 里）。它必须与上表同量级放大，
#: 否则"剩余额度 - 预留"会把节点额度压回 1_000 的下限——那比原来的 20k 更糟。
#:
#: **但它是一个上限，不是一个绝对值**（2026-11-09 真机复现）：
#: `REPOLEARN_JOB_MAX_TOKENS=180000`（旧默认值，也是很多机器的现状）时，
#: "剩余 132k - 预留 600k" 直接是负数 → 每个课时只拿到 1_000 token 的下限，
#: 于是**每一个课时一开口就超支**：
#:     budget exceeded: tokens used=7907 limit=1000
#: 整门课在 writer 第一个课时就死了，而用户只看到"预算耗尽"。
#: 预留必须按总闸的比例算（见 `JobBudget.per_lesson_reserve`）。
RESERVED_TOKENS = 600_000
#: 预留最多占总闸的这个比例。小预算配置下按比例缩，大预算时才用得上绝对值。
RESERVED_TOKENS_RATIO = 0.4


def estimate_tokens(text: str) -> int:
    """与 core 的 `estimatePromptTokens` 同口径（4 字符/token）。"""
    return max(1, (len(text or "") + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


@dataclass
class BudgetWarning:
    code: str
    message: str


@dataclass
class JobBudget:
    """Job 级总闸。由 runner 持有，每个节点出口检查一次。"""

    max_tokens: int = 2_000_000
    max_usd: float = 50.0
    deadline_ms: int = 1_500_000
    used_tokens: int = 0
    used_usd: float = 0.0
    started_at_ms: float = field(default_factory=monotonic_ms)
    warnings: list[BudgetWarning] = field(default_factory=list)

    def elapsed_ms(self) -> float:
        return monotonic_ms() - self.started_at_ms

    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    def remaining_ms(self) -> float:
        return max(0.0, self.deadline_ms - self.elapsed_ms())

    def per_lesson_reserve(self) -> int:
        """给"后面的课时"预留多少额度。

        为什么不能直接减 `RESERVED_TOKENS`（600k）：总闸是用户配的，配 180k 时
        "剩余 - 600k" 永远是负数，`node_allowance` 于是把**每个**课时压到 1_000
        token 的下限 —— 一个课时连读一个文件都不够，整门课在第一个课时就死。
        预留必须跟着总闸缩：小预算时按比例让出，大预算时才是那个绝对值。
        """
        return min(RESERVED_TOKENS, int(self.max_tokens * RESERVED_TOKENS_RATIO))

    def node_allowance(self, node: str, per_lesson: bool = False) -> int:
        """给某个节点下发的上限 = min(节点分闸, 剩余额度)。"""
        node_cap = NODE_BUDGETS.get(node, 8_000)
        available = self.remaining_tokens() - self.per_lesson_reserve() if per_lesson else self.remaining_tokens()
        return max(1_000, min(node_cap, available))

    def node_max_turns(self, node: str) -> int:
        """该节点的工具循环轮数上限。

        与 `node_allowance` 是一对：token 额度管"这一次能花多少"，轮数管
        "它能走多远"。只调前者等于给放大器换更大的桶。
        """
        return max(1, NODE_MAX_TURNS.get(node, DEFAULT_MAX_TURNS))

    def charge(self, tokens_in: int, tokens_out: int, usd: float = 0.0) -> None:
        self.used_tokens += max(0, tokens_in) + max(0, tokens_out)
        self.used_usd += max(0.0, usd)

    def exceeded(self) -> str | None:
        if self.used_tokens > self.max_tokens:
            return "tokens"
        if self.max_usd > 0 and self.used_usd > self.max_usd:
            return "usd"
        if self.elapsed_ms() > self.deadline_ms:
            return "deadline"
        return None

    def check(self) -> None:
        """超限即抛 `BUDGET_EXCEEDED`；runner 据此把 Job 置 `failed_budget`。

        提示里必须写清**是哪一档、怎么调**：用户看到
        `budget exceeded: tokens used=30212 limit=20000` 时，唯一能做的动作是去
        找那个 20000 在哪——所以把它对应的环境变量名直接写进 hint。
        """
        kind = self.exceeded()
        if kind:
            from repolearn.core.errors import AppError

            knobs = {
                "tokens": f"调大 .env 的 REPOLEARN_JOB_MAX_TOKENS（当前 {self.max_tokens}）",
                "usd": f"调大 .env 的 REPOLEARN_JOB_MAX_USD（当前 {self.max_usd}）",
                "deadline": f"调大 .env 的 REPOLEARN_JOB_DEADLINE_MS（当前 {self.deadline_ms}）",
            }
            used = {"tokens": self.used_tokens, "usd": round(self.used_usd, 4), "deadline": round(self.elapsed_ms())}[kind]
            raise AppError(
                "BUDGET_EXCEEDED",
                f"生成预算已耗尽（{kind}：已用 {used}，上限 {getattr(self, 'max_' + kind)}）",
                hint=f"{knobs[kind]}，改完重启 API；已生成的课时仍然可以学习",
                details={
                    "kind": kind,
                    "used_tokens": self.used_tokens,
                    "max_tokens": self.max_tokens,
                    "used_usd": round(self.used_usd, 6),
                    "max_usd": self.max_usd,
                },
            )

    def snapshot(self) -> dict:
        return {
            "max_tokens": self.max_tokens,
            "used_tokens": self.used_tokens,
            "max_usd": self.max_usd,
            "used_usd": round(self.used_usd, 6),
            "deadline_ms": self.deadline_ms,
            "elapsed_ms": round(self.elapsed_ms(), 1),
        }


@dataclass
class CallGuard:
    """单次调用的前置守卫：prompt 太大就直接拒绝，不花这笔钱。"""

    limit_tokens: int = 120_000
    warnings: list[BudgetWarning] = field(default_factory=list)

    def check_prompt(self, prompt: str) -> int:
        est = estimate_tokens(prompt)
        if est > self.limit_tokens:
            from repolearn.core.errors import AppError

            raise AppError(
                "BUDGET_EXCEEDED",
                f"单次 prompt 估算 {est} tokens，超过单次上限 {self.limit_tokens}",
                details={"estimated_tokens": est, "limit": self.limit_tokens},
            )
        return est


def usd_for(tokens_in: int, tokens_out: int, price_in: float, price_out: float) -> float:
    """只有两边价格都已知才计费；否则 0 并让调用方记 `PRICE_UNKNOWN`。"""
    if not price_in and not price_out:
        return 0.0
    return (tokens_in / 1_000_000) * price_in + (tokens_out / 1_000_000) * price_out
