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
NODE_BUDGETS: dict[str, int] = {
    "plan_curriculum": 20_000,
    "write_lessons": 9_000,
    "simulate_trace": 2_000,
    "synthesize_audio": 0,
    "analyze_repo": 4_000,
    # 预留 28k 给重试与修复（job 级 180k 的总闸在 JobBudget 里）
}
RESERVED_TOKENS = 28_000


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

    max_tokens: int = 180_000
    max_usd: float = 0.35
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
        """超限即抛 `BUDGET_EXCEEDED`；runner 据此把 Job 置 `failed_budget`。"""
        kind = self.exceeded()
        if kind:
            from repolearn.core.errors import AppError

            raise AppError(
                "BUDGET_EXCEEDED",
                f"生成预算已耗尽（{kind}）",
                details={"kind": kind, "used_tokens": self.used_tokens, "used_usd": round(self.used_usd, 6)},
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
