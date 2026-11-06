"""错误码与统一错误体（spec §5.6）。

设计要点：
* **HTTP 状态与 `code` 双语义**——状态码让代理/浏览器知道怎么处理，`code` 让
  前端决定展示哪段文案。只靠其中一个，前端就只能对状态码做 switch。
* `hint` 必须是**可执行的下一步**（"去设置里为 writer 角色选一个模型"），
  而不是"请稍后再试"。这是"稳健"在 UX 上唯一能被用户看见的地方。
* `retryable` **显式声明**，不从 HTTP 状态推断。推断会得出错误结论：
  `COURSE_NOT_READY` 是 409 但重试只会再拿到 409；`JOB_CONFLICT` 也是 409 但正确
  反应是"跳转到已有 job"而不是重试。前端拿这个布尔值决定"显示重试按钮还是跳转链接"。
* 19 个错误码是**定稿数量**，新增错误码必须同时加一条测试断言（§8.1）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ErrorSpec:
    http: int
    message: str
    hint: str | None = None
    retryable: bool = False


ERRORS: dict[str, ErrorSpec] = {
    "REPO_NOT_FOUND": ErrorSpec(404, "仓库不存在或不是公开仓库", "检查仓库地址拼写，并确认该仓库是公开的"),
    "REPO_FORBIDDEN": ErrorSpec(
        403, "无权访问该仓库", "私有仓库不在当前版本范围内；如需支持请配置 REPOLEARN_GITHUB_TOKEN"
    ),
    "RATE_LIMITED": ErrorSpec(
        429,
        "外部服务限流",
        "稍后重试；在 .env 配置 REPOLEARN_GITHUB_TOKEN 可将 GitHub 限额提升到 5000 次/小时",
        retryable=True,
    ),
    "REPO_TOO_LARGE": ErrorSpec(422, "仓库体量超过上限", "换一个更轻量的仓库，或调大 .env 里的 REPOLEARN_MAX_REPO_MB"),
    "NO_MODEL_FOR_ROLE": ErrorSpec(409, "有角色还没有配置模型", "去「设置 → 模型角色」为该角色选一个模型"),
    "SETUP_REQUIRED": ErrorSpec(428, "还没有完成 AI 服务配置", "打开 /setup 完成配置引导后再试"),
    "INVALID_KEY": ErrorSpec(401, "API Key 无效或已过期", "回到 /setup 的第二步重新填写 Key"),
    "PROVIDER_UNAVAILABLE": ErrorSpec(
        503, "模型服务暂时不可用", "可重试；若持续失败，在设置里切换到备用模型", retryable=True
    ),
    "BUDGET_EXCEEDED": ErrorSpec(
        402, "生成预算已耗尽", "在课程页点「继续生成」追加预算，或提高 .env 里的 REPOLEARN_JOB_MAX_TOKENS"
    ),
    "JOB_NOT_FOUND": ErrorSpec(404, "任务不存在", "刷新任务列表：GET /api/v1/jobs"),
    "JOB_CONFLICT": ErrorSpec(409, "同一份内容已有一个任务在排队或运行", "直接打开返回的 job_id 查看进度"),
    "COURSE_NOT_READY": ErrorSpec(409, "课程还没生成完成", "等生成任务结束后再打开（页面会显示进度）"),
    "ANCHOR_STALE": ErrorSpec(409, "课程锚点与当前 Commit 不一致", "重新生成这个仓库的课程"),
    "OBJECT_MISSING": ErrorSpec(404, "音频或 PDF 文件不存在", "可以在课程页重新生成音频，或在书籍页重新导出 PDF"),
    "INGEST_BLOCKED_PATH": ErrorSpec(422, "仓库中包含被安全策略拒绝的路径", "该路径已被跳过，不影响其余内容"),
    "CONTRACT_VIOLATION": ErrorSpec(
        502, "模型产出不符合结构契约", "已自动重试；若持续失败请在设置里换一个能力更强的模型", retryable=True
    ),
    "IDEMPOTENCY_MISMATCH": ErrorSpec(422, "同一个 Idempotency-Key 被用于了不同的请求内容", "为新的请求生成一个新的 Idempotency-Key"),
    "PROFILE_CONFLICT": ErrorSpec(
        409, "同时有另一个模型配置正在被激活", "重试即可；系统不会留下两个同时生效的配置", retryable=True
    ),
    "INTERNAL": ErrorSpec(500, "服务内部错误", "把页面上显示的 req_id 提供给维护者，可在 var/logs/api.log 中定位", retryable=True),
}

# 门禁：错误码数量必须与规范一致，改这里就必须同步改测试（§8.1）
ERROR_CODE_COUNT = 19


class AppError(Exception):
    """业务异常。所有对外错误都必须经过它，router 里不抛裸 `HTTPException`。"""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        hint: str | None = None,
        retryable: bool | None = None,
        status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        spec = ERRORS.get(code, ERRORS["INTERNAL"])
        self.code = code if code in ERRORS else "INTERNAL"
        self.status = status or spec.http
        self.message = message or spec.message
        self.hint = hint if hint is not None else spec.hint
        self.retryable = retryable if retryable is not None else spec.retryable
        self.details = details or {}
        super().__init__(self.message)

    def to_body(self, req_id: str | None = None) -> dict[str, Any]:
        err: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.hint:
            err["hint"] = self.hint
        if self.details:
            err["details"] = self.details
        err["req_id"] = req_id or "-"
        return {"error": err}


@dataclass
class PreflightGates:
    """Gate 0 结论（spec §2.4），供 /healthz 与 Doctor 面板共用。"""

    g1: str = "unknown"
    g2: str = "unknown"
    g3: str = "unknown"
    detail: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"g1": self.g1, "g2": self.g2, "g3": self.g3, **({"detail": self.detail} if self.detail else {})}
