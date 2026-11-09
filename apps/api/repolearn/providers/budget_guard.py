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

#: 节点级分闸（spec §3.4）。任一节点超限只让**该课时**失败，不拖垮整门课程。
#:
#: 2026-11-09 放宽：v1 的 `plan_curriculum=20_000` 在真实仓库上**必定撞墙**——
#: 一次规划要把知识图谱摘要 + 锚点 + 候选文件清单塞进 prompt，实测单次已用
#: 30_212 tokens（sherlock-project/sherlock，51 个文件、65 个符号），于是课程
#: 刚过 N5 就 `failed_budget`。真实链路自己量出来的数是这个常量的事后证据，
#: 但它说明的是**数量级错了**（估 20k、实际 30k+ 且随仓库规模增长），不是"运气差"。
#: 现在的值给到 10 倍量级，配合 `REPOLEARN_JOB_MAX_TOKENS`（总闸）一起收紧，
#: 而不是靠节点分闸去兜总账。
NODE_BUDGETS: dict[str, int] = {
    "plan_curriculum": 200_000,
    "write_lessons": 120_000,
    "simulate_trace": 20_000,
    "synthesize_audio": 0,
    "analyze_repo": 40_000,
}
#: 给后续课时留的余量（job 级总闸在 `JobBudget` 里）。它必须与上表同量级放大，
#: 否则"剩余额度 - 预留"会把节点额度压回 1_000 的下限——那比原来的 20k 更糟。
RESERVED_TOKENS = 400_000


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

    def node_allowance(self, node: str, per_lesson: bool = False) -> int:
        """给某个节点下发的上限 = min(节点分闸, 剩余额度)。"""
        node_cap = NODE_BUDGETS.get(node, 8_000)
        return max(1_000, min(node_cap, self.remaining_tokens() - RESERVED_TOKENS if per_lesson else self.remaining_tokens()))

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
