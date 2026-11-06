"""AgentRuntime 三个实现与三分支选择（spec §3.5.3，v2 修正 P1-8）。

这里最重要的不是代码量，而是**失败域的定义**。v1 把 `ExecCliRuntime` 描述成
"Kernel 不可用时的降级路径"，但 `aragon` CLI 与 `@aragon-agent/core` 来自同一个
包、同一个 registry——"包拉不下来"这一最可能的事故里，两条路会同时失效，降级链
给的是假的安全感。

真实可用的判断是三分支：

| 状态 | 判据 | 走哪条路 | 用户看到 |
|---|---|---|---|
| A 正常 | `/healthz` 通 且 coreVersion 匹配 | `HttpKernelRuntime` | 无提示 |
| B 包在但 Kernel 挂了 | `node -e import(core)` 成功，`/healthz` 2 秒不通 | `ExecCliRuntime` | 设置页"降级（CLI 直连）" |
| C 包不可用 | `node -e import(core)` 失败 | **模板降级**（不尝试 exec） | "课程为简化版" |

选择策略由 `REPOLEARN_AGENT_RUNTIME` 决定（kernel|exec|template|auto）；`auto`
按 A→B→C 判定，结果在进程内缓存 60 秒——否则每个课时都要探测一次 Node 运行时。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from repolearn.core.clock import utcnow
from repolearn.core.config import settings
from repolearn.core.errors import AppError
from repolearn.core.logging import get_logger
from repolearn.providers.base import AgentBudget, AgentEvent, AgentRunRequest, AgentRunResult
from repolearn.providers.http import new_client

log = get_logger("agent_runtime")

CORE_PACKAGE = "@aragon-agent/core"
HEALTH_TIMEOUT_S = 2.0
PROBE_TTL_S = 60.0


# --------------------------------------------------------------------------- #
# 状态探测                                                                     #
# --------------------------------------------------------------------------- #


@dataclass
class RuntimeState:
    mode: str = "template"  # kernel | exec | template
    kernel_ok: bool = False
    core_available: bool = False
    core_version: str | None = None
    kernel_version: str | None = None
    reason: str = ""
    probed_at: float = 0.0

    @property
    def degraded(self) -> bool:
        return self.mode != "kernel"

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "kernel_ok": self.kernel_ok,
            "core_available": self.core_available,
            "core_version": self.core_version,
            "kernel_version": self.kernel_version,
            "reason": self.reason,
        }


_state = RuntimeState()
_state_lock = asyncio.Lock()


async def probe_kernel() -> tuple[bool, str | None]:
    """2 秒超时的健康探测。超时就是"不通"——不允许无限等待把启动拖死。"""
    url = f"{settings.kernel_url.rstrip('/')}/healthz"
    try:
        async with new_client(timeout_read=HEALTH_TIMEOUT_S) as client:
            resp = await client.get(url, timeout=HEALTH_TIMEOUT_S)
            if resp.status_code != 200:
                return False, None
            data = resp.json()
            return bool(data.get("coreAvailable", True)), data.get("coreVersion")
    except Exception:  # noqa: BLE001 - 任何异常都等价于"不通"
        return False, None


async def probe_core_package() -> tuple[bool, str | None]:
    """检查 `@aragon-agent/core` 是否真的可 import。

    **调用 `scripts/probe_core.mjs`，不在 Python 里拼 node 一行命令。** 原因是这条
    探测有三个坑（package.json 未被 exports 暴露、ESM 只有 import 条件、
    裸 import 相对脚本文件解析），三坑都会让结果变成"装好了却报 missing"——
    而 missing 的后果是整门课程静默降级为模板版。探测逻辑只能有一份。
    """
    node = shutil.which("node")
    if not node:
        return False, None
    script = settings.repo_root / "scripts" / "probe_core.mjs"
    kernel_dir = settings.repo_root / "services" / "agent-kernel"
    if not script.is_file() or not kernel_dir.is_dir():
        return False, None
    try:
        proc = await asyncio.create_subprocess_exec(
            node,
            str(script),
            str(kernel_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except Exception:  # noqa: BLE001 - 超时/无法启动都等价于"不可用"
        return False, None
    text = (out or b"").decode("utf-8", "ignore").strip().splitlines()
    if not text:
        return False, None
    try:
        payload = json.loads(text[-1])
    except json.JSONDecodeError:
        return False, None
    if not payload.get("ok"):
        log.warning("core_probe_failed", reason=str(payload.get("reason", ""))[:200])
        return False, None
    return True, payload.get("version")


async def refresh_state(force: bool = False) -> RuntimeState:
    """按 A→B→C 判定当前可用性。结果缓存 60 秒。"""
    global _state
    async with _state_lock:
        if not force and (time.monotonic() - _state.probed_at) < PROBE_TTL_S and _state.probed_at > 0:
            return _state
        kernel_ok, kernel_version = await probe_kernel()
        core_ok, core_version = await probe_core_package()
        configured = settings.agent_runtime

        if configured == "kernel":
            mode, reason = ("kernel" if kernel_ok else "exec" if core_ok else "template"), "配置为 kernel"
        elif configured == "exec":
            mode, reason = ("exec" if core_ok else "template"), "配置为 exec"
        elif configured == "template":
            mode, reason = "template", "配置为 template（强制模板降级）"
        else:
            if kernel_ok:
                mode, reason = "kernel", "Kernel 可用"
            elif core_ok:
                mode, reason = "exec", "Kernel 不可达但 core 包可用 → CLI 直连"
            else:
                mode, reason = "template", "core 包不可用 → 模板降级（不尝试 exec）"

        previous = _state.mode
        _state = RuntimeState(
            mode=mode,
            kernel_ok=kernel_ok,
            core_available=core_ok,
            core_version=core_version,
            kernel_version=kernel_version,
            reason=reason,
            probed_at=time.monotonic(),
        )
        if previous != mode and previous:
            log.warning("runtime_mode_changed", previous=previous, current=mode, reason=reason)
        return _state


def current_state() -> RuntimeState:
    return _state


def reset_state_for_tests() -> None:
    global _state
    _state = RuntimeState()


# --------------------------------------------------------------------------- #
# A · HttpKernelRuntime                                                        #
# --------------------------------------------------------------------------- #


class HttpKernelRuntime:
    name = "kernel"

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or settings.kernel_url).rstrip("/")
        self.token = token if token is not None else settings.internal_token

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.token:
            headers["X-Internal-Token"] = self.token
        return headers

    async def available(self) -> bool:
        ok, _ = await probe_kernel()
        return ok

    def _payload(self, req: AgentRunRequest) -> dict:
        return {
            "runId": req.run_id,
            "role": req.role,
            "provider": {
                "id": req.config.provider or "custom",
                "protocol": req.config.protocol,
                "baseUrl": req.config.base_url,
                "apiKey": req.config.api_key,
                "modelId": req.config.model_id,
            },
            "systemPrompt": req.system_prompt,
            "prompt": req.prompt,
            "tools": req.tools,
            "schemaRef": req.schema_ref,
            "budget": req.budget.as_kernel_payload(),
            "workspace": {"mirrorDir": req.mirror_dir},
            "metadata": {"job_id": req.job_id, **req.metadata},
        }

    async def run(self, req: AgentRunRequest) -> tuple[list[AgentEvent], AgentRunResult]:
        events: list[AgentEvent] = []
        result = AgentRunResult(status="failed", runtime=self.name)
        url = f"{self.base_url}/v1/run"
        attempts = 0
        async with new_client(timeout_read=(req.budget.deadline_ms / 1000) + 30) as client:
            while attempts < 2:
                attempts += 1
                try:
                    async with client.stream("POST", url, json=self._payload(req), headers=self._headers()) as resp:
                        if resp.status_code >= 400:
                            body = (await resp.aread()).decode("utf-8", "ignore")
                            result.error = {"code": "KERNEL_ERROR", "message": body[:400]}
                            if resp.status_code >= 500 and attempts < 2:
                                continue
                            return events, result
                        buffer = ""
                        async for raw in resp.aiter_text():
                            buffer += raw
                            while "\n\n" in buffer:
                                frame, _, buffer = buffer.partition("\n\n")
                                parsed = _parse_sse(frame)
                                if parsed is None:
                                    continue
                                events.append(parsed)
                                if parsed.type == "run.completed":
                                    result = AgentRunResult(
                                        status="completed",
                                        result=dict(parsed.data.get("result") or {}),
                                        usage=dict(parsed.data.get("usage") or {}),
                                        runtime=self.name,
                                    )
                                elif parsed.type == "run.failed":
                                    result = AgentRunResult(
                                        status=(
                                            "budget_exceeded"
                                            if parsed.data.get("code") == "BUDGET_EXCEEDED"
                                            else "cancelled"
                                            if parsed.data.get("code") == "CANCELLED"
                                            else "degraded"
                                            if parsed.data.get("code") == "CORE_UNAVAILABLE"
                                            else "failed"
                                        ),
                                        usage=dict(parsed.data.get("usage") or {}),
                                        error={
                                            "code": parsed.data.get("code", "KERNEL_RUN_FAILED"),
                                            "message": parsed.data.get("message", ""),
                                        },
                                        runtime=self.name,
                                    )
                                elif parsed.type == "budget.exceeded":
                                    result = AgentRunResult(
                                        status="budget_exceeded",
                                        error={
                                            "code": "BUDGET_EXCEEDED",
                                            "message": str(parsed.data.get("kind", "budget")),
                                        },
                                        runtime=self.name,
                                    )
                    return events, result
                except Exception as exc:  # noqa: BLE001 - 网络异常按"重试一次"处理
                    if attempts >= 2:
                        result.error = {"code": "PROVIDER_UNAVAILABLE", "message": str(exc)[:300]}
                        return events, result
                    await asyncio.sleep(1.0)
        return events, result

    async def cancel(self, run_id: str) -> None:
        url = f"{self.base_url}/v1/run/{run_id}/cancel"
        try:
            async with new_client(timeout_read=5.0) as client:
                await client.post(url, headers=self._headers())
        except Exception:  # noqa: BLE001 - 取消失败不改变本地终态判定
            pass


def _parse_sse(frame: str) -> AgentEvent | None:
    """解析 `id: N\\nevent: type\\ndata: {...}` 帧。坏帧丢弃而不是崩溃。"""
    event_type = ""
    data_line = ""
    seq = 0
    for line in frame.splitlines():
        if line.startswith(":"):
            continue
        if line.startswith("id:"):
            try:
                seq = int(line[3:].strip())
            except ValueError:
                seq = 0
        elif line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_line += line[5:].strip()
    if not event_type and not data_line:
        return None
    payload: dict = {}
    if data_line:
        try:
            payload = json.loads(data_line)
        except json.JSONDecodeError:
            payload = {}
    return AgentEvent(
        type=event_type or str(payload.get("type", "unknown")),
        seq=seq or int(payload.get("seq", 0) or 0),
        ts=int(payload.get("ts", 0) or 0),
        data=dict(payload.get("data") or {}),
    )


# --------------------------------------------------------------------------- #
# B · ExecCliRuntime                                                           #
# --------------------------------------------------------------------------- #


class ExecCliRuntime:
    """`npx aragon exec --output-format stream-json`（条件性兜底）。

    **只在"包已安装、Kernel 进程挂了"时有用**。包不可用时它和 Kernel 一起失效，
    因此 `RuntimeSelector` 在状态 C 下**不会**选它（spec §3.5.3）。
    """

    name = "exec"

    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd or str(settings.repo_root / "services" / "agent-kernel")
        self._running: dict[str, asyncio.subprocess.Process] = {}

    async def available(self) -> bool:
        ok, _ = await probe_core_package()
        return ok and shutil.which("node") is not None

    async def run(self, req: AgentRunRequest) -> tuple[list[AgentEvent], AgentRunResult]:
        events: list[AgentEvent] = []
        npx = shutil.which("npx")
        if not npx:
            return events, AgentRunResult(
                status="failed",
                error={"code": "EXEC_UNAVAILABLE", "message": "未找到 npx"},
                runtime=self.name,
            )
        args = [
            npx,
            "aragon",
            "exec",
            "--output-format",
            "stream-json",
            "--permission-mode",
            "plan",
            req.prompt,
        ]
        env_note = {k: v for k, v in req.metadata.items() if isinstance(v, str)}
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=self.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**_base_env(), **{f"ARAGON_{k.upper()}": v for k, v in env_note.items()}},
            )
        except Exception as exc:  # noqa: BLE001
            return events, AgentRunResult(
                status="failed", error={"code": "EXEC_UNAVAILABLE", "message": str(exc)[:300]}, runtime=self.name
            )
        self._running[req.run_id] = proc
        deadline = req.budget.deadline_ms / 1000
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=deadline)
        except TimeoutError:
            proc.kill()
            return events, AgentRunResult(
                status="budget_exceeded",
                error={"code": "BUDGET_EXCEEDED", "message": "CLI 执行超时"},
                runtime=self.name,
            )
        finally:
            self._running.pop(req.run_id, None)
        seq = 0
        for line in (out or b"").decode("utf-8", "ignore").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            seq += 1
            events.append(AgentEvent(type=str(obj.get("type", "unknown")), seq=seq, ts=int(obj.get("ts", 0) or 0), data=obj))
        if proc.returncode == 0:
            return events, AgentRunResult(status="completed", result={"raw": events[-1].data if events else {}}, runtime=self.name)
        return events, AgentRunResult(
            status="failed",
            error={"code": "EXEC_FAILED", "message": (err or b"").decode("utf-8", "ignore")[:300]},
            runtime=self.name,
        )

    async def cancel(self, run_id: str) -> None:
        proc = self._running.get(run_id)
        if proc and proc.returncode is None:
            proc.kill()


def _base_env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if isinstance(v, str)}


# --------------------------------------------------------------------------- #
# 选择器                                                                       #
# --------------------------------------------------------------------------- #


@dataclass
class RuntimeSelector:
    """按状态把 run 分发到正确的实现。

    `template_factory` 由 workflow 注入：模板降级的产出规则必须写死（spec §3.5.4），
    而那套规则属于课程领域，不属于这里。
    """

    kernel: HttpKernelRuntime = field(default_factory=HttpKernelRuntime)
    exec_cli: ExecCliRuntime = field(default_factory=ExecCliRuntime)
    template_factory: Callable[[], object] | None = None

    async def pick(self) -> str:
        state = await refresh_state()
        return state.mode

    async def run(self, req: AgentRunRequest) -> tuple[list[AgentEvent], AgentRunResult]:
        state = await refresh_state()
        if state.mode == "kernel":
            events, result = await self.kernel.run(req)
            if result.status in ("degraded", "failed") and result.error and result.error.get("code") == "CORE_UNAVAILABLE":
                # Kernel 进程活着但 core 不可用 → 直接进 C（不尝试 exec）
                return events, AgentRunResult(
                    status="degraded",
                    result=result.result,
                    usage=result.usage,
                    error={"code": "CORE_UNAVAILABLE", "message": state.reason},
                    runtime="template",
                )
            return events, result
        if state.mode == "exec":
            return await self.exec_cli.run(req)
        return [], AgentRunResult(
            status="degraded",
            error={"code": "CORE_UNAVAILABLE", "message": state.reason},
            runtime="template",
        )

    async def cancel(self, run_id: str) -> None:
        await asyncio.gather(self.kernel.cancel(run_id), self.exec_cli.cancel(run_id), return_exceptions=True)


_selector: RuntimeSelector | None = None


def get_selector() -> RuntimeSelector:
    global _selector
    if _selector is None:
        _selector = RuntimeSelector()
    return _selector


def reset_selector_for_tests() -> None:
    global _selector
    _selector = None


async def runtime_report() -> dict:
    state = await refresh_state()
    return state.as_dict()


def ensure_run_id(prefix: str = "run") -> str:
    from repolearn.core.ids import new_id

    return new_id(prefix)


__all__ = [
    "AgentBudget",
    "AgentEvent",
    "AgentRunRequest",
    "AgentRunResult",
    "AppError",
    "ExecCliRuntime",
    "HttpKernelRuntime",
    "RuntimeSelector",
    "RuntimeState",
    "current_state",
    "ensure_run_id",
    "get_selector",
    "probe_core_package",
    "probe_kernel",
    "refresh_state",
    "reset_selector_for_tests",
    "reset_state_for_tests",
    "runtime_report",
    "utcnow",
]
