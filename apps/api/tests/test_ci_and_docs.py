"""CI 流水线与文档门禁（spec §7.2 的 `T-CI-1..6` / `T-DOC-1` / `T-DOC-2`）。

这一组的共同点：**它们断言的都是"文件里写了什么"**，而不是"代码跑得对不对"。
这看起来弱，但本轮的失败形态恰好是"方案写了、工具清单/流水线没接上"——CI 少一个
job、加了 devDependency 没更新 lockfile、Node 版本写回 20、文档里的数字与实测不符。
这些都不能靠"读代码"发现，只能靠把文本当契约来断言。

实现方式（spec §10 第 4 条）：**用 `pathlib` 读文件做文本断言，不引入 PyYAML**。
理由：`pyyaml` 会为一个测试引入新依赖，而它只能验证"文件里写了什么"，并不能验证
"GitHub 真的会跑"。文本断言 + 首次真跑是双保险；要严格校验上 `actionlint`
（独立工具，不进 Python 依赖）。

`T-DOC-1` 的 P1-11 约束：pytest 的收集数**依赖平台**（`test_scripts_and_seed.py`
在非 Windows 上 skip），因此只在 Windows 上比对，非 Windows `pytest.skip`——与
`test_scripts_and_seed.py` 的既有策略一致。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from repolearn.core.config import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
README = REPO_ROOT / "README.md"
LOCKFILE = REPO_ROOT / "pnpm-lock.yaml"
WEB_PKG = REPO_ROOT / "apps" / "web" / "package.json"
KERNEL_PKG = REPO_ROOT / "services" / "agent-kernel" / "package.json"
SPEC = REPO_ROOT / "docs" / "plans" / "repo-learn-hardening" / "spec.md"
COUNT_SCRIPT = REPO_ROOT / "scripts" / "count_workfiles.py"

#: spec §3.2.4 的六个 job。`gates` 是唯一 required check，其余五个是它 `needs` 的对象。
REQUIRED_JOBS = ("api", "kernel", "web", "e2e-offline", "e2e-real", "gates")
GATE_NEEDED_JOBS = tuple(name for name in REQUIRED_JOBS if name != "gates")

#: spec §3.2.4 / §4.6 #85：本轮新增的 devDependency（与 lockfile 必须同一次提交）。
NEW_DEV_DEP = "@axe-core/playwright"
PINNED_PNPM = "12.18.0"


def _read(path: Path) -> str:
    """统一用 UTF-8 读；CI 的 checkout 在 Windows 上也是 LF，不需要额外处理。"""
    return path.read_text(encoding="utf-8")


def _workflow_text() -> str:
    assert WORKFLOW.is_file(), f"缺少 CI 定义：{WORKFLOW}"
    return _read(WORKFLOW)


def _job_block(text: str, job: str) -> str:
    """截出顶层 `  <job>:` 这一节（到下一个同级 job 之前）。

    只做文本切片，不做 YAML 解析：本组测试要的就是"文件里有没有这段文字"。
    """
    match = re.search(rf"^  {re.escape(job)}:\s*$", text, re.MULTILINE)
    assert match, f"ci.yml 里找不到 job `{job}`（T-CI-1：六个 job 少一个就是少一条门禁）"
    rest = text[match.end() :]
    next_job = re.search(r"^  [A-Za-z0-9_-]+:\s*$", rest, re.MULTILINE)
    return rest[: next_job.start()] if next_job else rest


def _parse_needs(block: str) -> list[str]:
    """解析 `needs:`，同时支持流式 `[a, b]` 与块式 `- a` 两种写法。"""
    flow = re.search(r"^\s*needs:\s*\[(?P<items>[^\]]*)\]", block, re.MULTILINE)
    if flow:
        return [item.strip().strip("'\"") for item in flow.group("items").split(",") if item.strip()]
    block_style = re.search(r"^\s*needs:\s*$\n(?P<items>(?:\s*-\s*\S+\s*\n)+)", block, re.MULTILINE)
    if block_style:
        return [line.strip().lstrip("-").strip().strip("'\"") for line in block_style.group("items").splitlines()]
    return []


# --------------------------------------------------------------------------- T-CI-1
def test_ci_workflow_has_required_jobs():
    """`T-CI-1`：六个 job key 全在。

    最容易被悄悄删掉的是 `e2e-real`（它最慢、最需要三进程），所以这条不能省。
    """
    text = _workflow_text()
    missing = [job for job in REQUIRED_JOBS if not re.search(rf"^  {re.escape(job)}:\s*$", text, re.MULTILINE)]
    assert not missing, f"ci.yml 缺少 job：{missing}（spec §3.2.4 要求六个）"


# --------------------------------------------------------------------------- T-CI-2
def test_ci_runs_all_gates():
    """`T-CI-2`：六条门禁命令都接进了流水线（写了却没接 = 等于没写）。"""
    text = _workflow_text()
    required = {
        "契约漂移": "export-openapi --check",
        "前端契约": "contracts:check",
        "类型检查": "tsc --noEmit",
        "前端单测": "vitest run",
        "离线 E2E": "playwright test",
        "真链路 E2E": "node scripts/e2e-real.mjs",
    }
    missing = [f"{label}（{needle}）" for label, needle in required.items() if needle not in text]
    assert not missing, f"ci.yml 里没有接上这些门禁：{missing}"


# --------------------------------------------------------------------------- T-CI-3
def test_ci_uploads_artifacts_and_cancels():
    """`T-CI-3`：失败现场能拿到（artifact）+ 连续 push 不堆积（concurrency）。"""
    text = _workflow_text()
    assert "actions/upload-artifact" in text, "失败时没有 trace/report 可查（缺 actions/upload-artifact）"
    assert "concurrency" in text, "缺 concurrency：PR 连续 push 会堆积多份流水线"
    assert "cancel-in-progress" in text, "缺 cancel-in-progress：上一轮不会被取消"
    # 失败域的落点：e2e-real 必须留下 var/e2e 的日志（spec §3.2.6）
    assert "var/e2e" in text, "e2e-real 失败时没有上传 var/e2e 日志"


# --------------------------------------------------------------------------- T-CI-4
def test_ci_required_gate_job():
    """`T-CI-4`：`gates` 的 `needs` 覆盖其余五个。

    漏配一个 = 那个 job 挂了但 required check 仍是绿的（幽灵绿灯），这比没有门禁更坏。
    """
    text = _workflow_text()
    needs = _parse_needs(_job_block(text, "gates"))
    missing = [job for job in GATE_NEEDED_JOBS if job not in needs]
    assert not missing, f"`gates` job 的 needs 未覆盖：{missing}（实际 needs={needs}）"
    # 反向：needs 里不该出现不存在的 job（拼错的名字同样是幽灵绿灯）
    unknown = [job for job in needs if job not in REQUIRED_JOBS]
    assert not unknown, f"`gates` job 的 needs 里有 ci.yml 中不存在的 job：{unknown}"


# --------------------------------------------------------------------------- T-CI-5
def test_lockfile_has_new_devdep():
    """`T-CI-5`：lockfile 与 devDependency 必须同时到位（评审 P1-3）。

    只改 `apps/web/package.json` 而不重新生成 `pnpm-lock.yaml`，
    `pnpm install --frozen-lockfile` 首跑就红——而那个报错看起来与代码毫无关系。
    """
    lock_text = _read(LOCKFILE)
    # lockfile 里出现的是 `'@axe-core/playwright':` 这样的键，不是任意一处提及
    assert NEW_DEV_DEP in lock_text, (
        f"pnpm-lock.yaml 里没有 {NEW_DEV_DEP}：加了 devDependency 却没重新生成 lockfile，"
        "`pnpm install --frozen-lockfile` 会失败"
    )

    web_pkg = json.loads(_read(WEB_PKG))
    dev_deps = web_pkg.get("devDependencies") or {}
    assert NEW_DEV_DEP in dev_deps, (
        f"apps/web/package.json 的 devDependencies 里没有 {NEW_DEV_DEP}"
        f"（实际：{sorted(dev_deps)}）"
    )
    # 只进 devDeps：进 dependencies 会被打进产物 bundle。
    assert NEW_DEV_DEP not in (web_pkg.get("dependencies") or {}), (
        f"{NEW_DEV_DEP} 不该出现在 dependencies 里（只管测试用）"
    )

    # 声明与锁定必须指同一条大版本线，否则 `--frozen-lockfile` 一样会拒绝。
    declared = str(dev_deps[NEW_DEV_DEP]).lstrip("^~")
    lock_entry = re.search(rf"'{re.escape(NEW_DEV_DEP)}':\s*\n?\s*specifier:\s*(?P<spec>\S+)", lock_text)
    if lock_entry:
        locked_spec = lock_entry.group("spec").strip("'\"")
        assert locked_spec.lstrip("^~") == declared, (
            f"package.json 声明 {dev_deps[NEW_DEV_DEP]} 与 lockfile 的 specifier "
            f"{locked_spec} 不一致：lockfile 没跟着一起更新"
        )


# --------------------------------------------------------------------------- T-CI-6
def test_ci_node_and_pnpm_pinned():
    """`T-CI-6`：Node 一律 22、pnpm 显式 pin（评审 P1-2 / P1-3）。

    kernel 的 `npm test` 走 `--experimental-strip-types`，Node 20 上直接失败；
    pnpm 版本靠 corepack 猜测时，失败表现是"lockfile 版本不兼容"，与代码无关。
    """
    text = _workflow_text()
    assert "node-version: 20" not in text, "ci.yml 里仍有 node-version: 20：kernel job 必挂（Node 22.6 才是下限）"
    assert "node-version: 22" in text, "ci.yml 里没有 node-version: 22"
    assert f"version: {PINNED_PNPM}" in text, (
        f"ci.yml 里没有把 pnpm pin 到 `version: {PINNED_PNPM}`（与根 package.json 的 packageManager 一致）"
    )
    assert "pnpm/action-setup" in text, "缺 pnpm/action-setup：不 pin 就依赖 runner 的 corepack 猜测"

    # P1-2 的另一半：engines.node 是给开发机看的同一条下限，漏了它就只剩 CI 一层拦截。
    kernel_pkg = json.loads(_read(KERNEL_PKG))
    engines = kernel_pkg.get("engines") or {}
    assert engines.get("node") == ">=22.6", (
        f"services/agent-kernel/package.json 的 engines.node 应为 >=22.6（实际 {engines.get('node')!r}）"
    )


# --------------------------------------------------------------------------- T-DOC-1
#: README §5 的测试矩阵行，形如
#: `测试现状（本机实测）：**197 pytest + 37 kernel + 62 vitest + 14 playwright** 全绿。`
README_MATRIX_RE = re.compile(
    r"\*\*\s*(\d+)\s*pytest\s*\+\s*(\d+)\s*kernel\s*\+\s*(\d+)\s*vitest\s*\+\s*(\d+)\s*playwright\s*\*\*"
)
COLLECTED_RE = re.compile(r"(\d+)\s+tests?\s+collected")


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="T-DOC-1 只在 Windows 上执行：pytest 收集数依赖平台（test_scripts_and_seed.py 在非 Windows 上 skip），跨平台比数字是伪命题（spec 评审 P1-11）",
)
def test_readme_test_matrix_matches_repo():
    """`T-DOC-1`：README 里写的 pytest 收集数必须与本机实测一致。

    只比对 **pytest** 这一项：kernel（`npm test`）/ vitest / playwright 的计数要跑
    npm 与浏览器，在这条门禁里跑它们是"用几十秒换一个数字"，而且会让 `api` job
    突然依赖 Node 与 Chromium——那正是本组测试要避免的形态。因此：

    * pytest：**实测**（`python -m pytest --collect-only -q`）；
    * kernel / vitest / playwright：从 README 解析出来，但**不比对数**（注释见下）。

    这条测试红的时候，说明"文档在说谎"——修法是更新 README 的数字，
    **不是**放宽断言。README 归文档节点所有，这里只负责把它钉住。
    """
    readme = _read(README)
    match = README_MATRIX_RE.search(readme)
    assert match, (
        "README 里找不到测试矩阵行（形如 `**197 pytest + 37 kernel + 62 vitest + 14 playwright**`）；"
        "该行是 T-DOC-1 的锚点，不要改掉它的格式"
    )
    readme_pytest, readme_kernel, readme_vitest, readme_playwright = (int(g) for g in match.groups())

    # kernel / vitest / playwright 三项本轮不实测（理由见 docstring）。这里只做
    # "数字存在且为正"的弱校验，防止有人在更新 README 时把它们写成 0 或删掉。
    weak = {"kernel": readme_kernel, "vitest": readme_vitest, "playwright": readme_playwright}
    zeroed = [name for name, value in weak.items() if value <= 0]
    assert not zeroed, f"README 测试矩阵里这些数字不合法：{zeroed}（实际 {weak}）"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    output = f"{result.stdout}\n{result.stderr}"
    collected_match = COLLECTED_RE.search(output)
    if collected_match:
        collected = int(collected_match.group(1))
    else:
        # 兜底：`-q` 的输出是一行一个 nodeid（`path::name`）。
        collected = sum(1 for line in result.stdout.splitlines() if "::" in line)
    assert collected > 0, f"没解析出 pytest 收集数（退出码 {result.returncode}）：{output[-1200:]}"

    assert readme_pytest == collected, (
        f"README 写 {readme_pytest} 条 pytest，实测收集 {collected} 条（差 {collected - readme_pytest}）。"
        "请把 README §5「测试现状」的数字改成实测值——本项目不能有"
        "「文档里的数字与仓库不符」这种缺陷（spec T-DOC-1 / A10）"
    )


# --------------------------------------------------------------------------- T-DOC-2
COUNT_LINE_RE = re.compile(r"^rows=(?P<rows>\d+) unique=(?P<unique>\d+) 新=(?P<new>\d+) 改=(?P<edit>\d+) 生成=(?P<gen>\d+)$")
SPEC_ROWS_RE = re.compile(r"\*\*(?P<rows>\d+) 行 / (?P<unique>\d+) 个唯一文件\*\*")
SPEC_KINDS_RE = re.compile(r"按类型：\*\*新建 (?P<new>\d+)、修改 (?P<edit>\d+)、生成 (?P<gen>\d+)\*\*")


def test_spec_workfile_matrix_is_consistent():
    """`T-DOC-2`：§4.6 末行"规模"段的五个数字 = `count_workfiles.py` 的实算值。

    评审 P2-1 的教训：v1 的"75 行 / 68 唯一 / 33+32+3"三个口径互相打架，读者无法
    判断"到底要动几个文件"。所以 v2 不给手写数字，给**唯一算法**——本测试就是它的门禁。
    """
    assert COUNT_SCRIPT.is_file(), f"缺少脚本：{COUNT_SCRIPT}"
    result = subprocess.run(
        [sys.executable, str(COUNT_SCRIPT), str(SPEC)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, (
        f"count_workfiles.py 退出码 {result.returncode}：{(result.stdout + result.stderr)[-800:]}"
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "count_workfiles.py 没有任何输出"
    match = COUNT_LINE_RE.match(lines[-1].strip())
    assert match, f"count_workfiles.py 的输出形状不是 `rows=.. unique=.. 新=.. 改=.. 生成=..`：{lines[-1]!r}"
    actual = {
        "rows": int(match.group("rows")),
        "unique": int(match.group("unique")),
        "新": int(match.group("new")),
        "改": int(match.group("edit")),
        "生成": int(match.group("gen")),
    }

    spec_text = _read(SPEC)
    rows_match = SPEC_ROWS_RE.search(spec_text)
    kinds_match = SPEC_KINDS_RE.search(spec_text)
    assert rows_match, "spec §4.6 里找不到「**N 行 / M 个唯一文件**」这一行（规模段的锚点）"
    assert kinds_match, "spec §4.6 里找不到「按类型：**新建 N、修改 M、生成 K**」"
    documented = {
        "rows": int(rows_match.group("rows")),
        "unique": int(rows_match.group("unique")),
        "新": int(kinds_match.group("new")),
        "改": int(kinds_match.group("edit")),
        "生成": int(kinds_match.group("gen")),
    }

    diff = {key: (documented[key], actual[key]) for key in actual if documented[key] != actual[key]}
    assert not diff, (
        "spec §4.6 末行「规模」与表格实际不符（文档值, 实算值）："
        f"{diff}；文档={documented}，实算={actual}。"
        "改法是更新 spec 里的数字（算法见 scripts/count_workfiles.py），不是放宽断言"
    )
