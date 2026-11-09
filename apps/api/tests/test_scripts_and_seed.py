"""启动脚本与种子数据的防回归（来自实跑 start.ps1 时暴露的三个缺陷）。

这三条都是"只在真机上跑一次才会发现"的问题，因此必须有静态/行为断言兜住：

1. `seed-demo` 曾经只能跑一次（第二次撞 `repositories.full_name` 唯一约束）；
2. `Start-Process -FilePath "pnpm"` 在 Windows 上必然失败（`.cmd`/`.ps1` 垫片不是
   可执行文件）→ `cmd.exe /c` 才是正确启动方式；
3. 机器上有全局 `NODE_ENV=production` 时，`next dev` 的 edge middleware 直接
   `EvalError: Code generation from strings disallowed`，每个请求 500。
"""

from __future__ import annotations

import re
from pathlib import Path

from repolearn.core.config import REPO_ROOT

START_PS1 = REPO_ROOT / "start.ps1"
STOP_PS1 = REPO_ROOT / "stop.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="ascii")


def test_seed_demo_is_idempotent():
    """连跑两次 `cli seed-demo` 都必须成功（start.ps1 与用户都会重复执行它）。"""
    from repolearn.cli import main

    assert main(["seed-demo"]) == 0
    assert main(["seed-demo"]) == 0


def test_seed_demo_creates_exactly_one_demo_course():
    import asyncio

    from sqlalchemy import func, select

    from repolearn.cli import main
    from repolearn.core.db import SessionMaker
    from repolearn.models import CourseVersion, Repository

    main(["seed-demo"])
    main(["seed-demo"])

    async def count() -> tuple[int, int]:
        async with SessionMaker() as session:
            repos = (
                await session.execute(
                    select(func.count(Repository.id)).where(Repository.full_name == "microsoft/autogen (demo)")
                )
            ).scalar()
            courses = (
                await session.execute(
                    select(func.count(CourseVersion.id)).where(
                        CourseVersion.title.like("AutoGen 带读%")
                    )
                )
            ).scalar()
            return int(repos or 0), int(courses or 0)

    repos, courses = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(count())
    assert repos == 1
    assert courses == 1


def test_start_ps1_launches_pnpm_through_cmd():
    """`Start-Process -FilePath pnpm` 在 Windows 上不可用（垫片不是 PE 文件）。"""
    text = _read(START_PS1)
    assert 'Start-Process -FilePath "cmd.exe"' in text
    # 通过 cmd.exe 拼参数行（反引号转义在 PowerShell 里表示字面引号）
    assert "argLine = '/c \"" in text
    # 不允许直接对 pnpm 垫片调 Start-Process
    assert not re.search(r'Start-Process\s+-FilePath\s+"?pnpm"?', text)


def test_start_ps1_pins_node_env():
    """全局 NODE_ENV 会让 `next dev` 的 middleware 崩掉，必须显式钉住。"""
    text = _read(START_PS1)
    assert '$env:NODE_ENV = "development"' in text
    assert '$env:NODE_ENV = "production"' in text


def test_start_ps1_preserves_env_encoding():
    """`.env` 的读写必须显式走**无 BOM 的 UTF-8**（这条是实际故障的回归）。

    故障链：PowerShell 5.1 的 `Get-Content -Raw` 用 ANSI 代码页读 UTF-8 文件，
    中文注释被解成乱码；`Set-Content -Encoding UTF8` 又写回 BOM。结果是
    * 文件头出现 BOM，pydantic-settings 读到的第一个键名变成 "\\ufeffREPOLEARN_ENV"；
    * 乱码注释吞掉换行，下一行的 `REPOLEARN_WEB_PORT=3000` 被并进注释里。
    症状是"我明明配了却没生效"，而配置本身看起来是存在的。
    """
    text = _read(START_PS1)
    assert "UTF8Encoding($false)" in text
    assert "[System.IO.File]::ReadAllText($envPath, $utf8NoBom)" in text
    assert "[System.IO.File]::WriteAllText($envPath, $envText, $utf8NoBom)" in text
    # 回退到这两行就等于把故障装回去：前者按 ANSI 解码，后者写 BOM。
    assert "Get-Content $envPath" not in text
    assert "Set-Content -Path $envPath" not in text


def test_start_ps1_refuses_to_run_on_busy_ports():
    text = _read(START_PS1)
    assert "Get-NetTCPConnection" in text
    assert "exit 2" in text


def test_start_ps1_writes_pid_files_and_ports_json():
    text = _read(START_PS1)
    assert "$runDir \"$Name.pid\"" in text or "Save-Pid" in text
    assert "ports.json" in text


def test_stop_ps1_kills_trees_and_sweeps_ports():
    text = _read(STOP_PS1)
    assert "taskkill /PID" in text and "/T /F" in text
    assert "Get-NetTCPConnection" in text


def test_scripts_are_parseable_by_powershell_51():
    """调用真实的 PS 解析器；解析不过说明语法在 5.1 上不成立。"""
    import subprocess

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "parse_check.ps1"),
        ],
        capture_output=True,
        timeout=180,
    )
    if result.returncode != 0:
        out = (result.stdout + result.stderr).decode("utf-8", "ignore")
        raise AssertionError(f"PowerShell 解析失败：{out[-800:]}")
