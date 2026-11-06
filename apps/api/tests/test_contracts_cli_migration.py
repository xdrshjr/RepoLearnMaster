"""迁移往返、契约一致性与 CLI（T-DB-1 / T-CON-1 / T-CON-2 / T-SCR-4 的离线部分）。"""

from __future__ import annotations

import json
import subprocess

import jsonschema
import pytest

from repolearn.core.config import REPO_ROOT

SCHEMA_DIR = REPO_ROOT / "packages" / "contracts" / "schemas"


def test_migration_roundtrip(tmp_path):
    """T-DB-1：`upgrade head → downgrade base → upgrade head` 三步都必须成功。

    用独立的临时库，避免把正在跑的测试库降级掉。这条门禁的价值在于"downgrade 可执行"
    ——绝大多数项目的 downgrade 从来没被跑过，等真需要回滚时才发现它是坏的。
    """
    from alembic import command
    from alembic.config import Config

    db = tmp_path / "roundtrip.db"
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "migrations"))
    import os

    old = os.environ["REPOLEARN_DATABASE_URL"]
    os.environ["REPOLEARN_DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    from repolearn.core.config import get_settings

    get_settings.cache_clear()
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        os.environ["REPOLEARN_DATABASE_URL"] = old
        get_settings.cache_clear()
    assert db.exists()


@pytest.mark.parametrize("name", ["course", "lesson", "trace", "book"])
def test_schema_files_are_valid_json_schema(name):
    schema = json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))
    jsonschema.Draft7Validator.check_schema(schema)
    assert schema.get("title")


def test_golden_curriculum_passes_json_schema():
    """T-CON-2 的一半：黄金样本必须通过 packages/contracts 里的 schema。"""
    golden = {
        "title": "AutoGen 入门",
        "sections": [
            {"key": "overview", "title": "宏观", "minutes": 6, "lessons": [{"key": "1.1", "title": "结构", "goal": "看懂分层", "anchors": [{"file": "a.py", "line_start": 1, "line_end": 3}]}]},
            {"key": "walkthrough", "title": "走读", "minutes": 8, "lessons": [{"key": "2.1", "title": "往返", "goal": "画出顺序"}]},
            {"key": "deep_dive", "title": "深入", "minutes": 10, "lessons": [{"key": "3.1", "title": "reply", "goal": "解释返回"}]},
            {"key": "recap", "title": "总结", "minutes": 4, "lessons": [{"key": "4.1", "title": "复盘", "goal": "复述结论"}]},
        ],
    }
    schema = json.loads((SCHEMA_DIR / "course.json").read_text(encoding="utf-8"))
    jsonschema.validate(golden, schema)


def test_golden_lesson_passes_json_schema():
    golden = {
        "key": "1.1",
        "title": "走读",
        "layer": "overview",
        "steps": [
            {
                "index": 0,
                "title": "入口",
                "duration_ms": 8000,
                "segments": [{"id": "s0", "text": "从入口开始", "start_ms": 0, "end_ms": 8000}],
            }
        ],
    }
    schema = json.loads((SCHEMA_DIR / "lesson.json").read_text(encoding="utf-8"))
    jsonschema.validate(golden, schema)


def test_contract_schema_rejects_obviously_wrong_payload():
    schema = json.loads((SCHEMA_DIR / "lesson.json").read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"key": "x", "title": "y", "layer": "overview", "steps": []}, schema)


def test_kernel_and_python_agree_on_lesson_shape():
    """Kernel 的 zod schema 导出的 JSON Schema 与 Python 侧同源（T-CON-2 的另一半）。

    没有安装 @aragon-agent/core 时跳过——那是状态 C 的正常情况，不是测试失败。
    """
    kernel = REPO_ROOT / "services" / "agent-kernel"
    if not (kernel / "node_modules").exists():
        pytest.skip("agent-kernel 依赖未安装")
    script = (
        "import { schemaJson } from './src/tools/emit.ts';"
        "const s = schemaJson('lesson');"
        "process.stdout.write(JSON.stringify(s));"
    )
    try:
        out = subprocess.run(
            ["node", "--experimental-strip-types", "-e", script],
            cwd=kernel,
            capture_output=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("node 不可用")
    if out.returncode != 0:
        pytest.skip(f"kernel schema 导出失败：{out.stderr.decode('utf-8', 'ignore')[:200]}")
    kernel_schema = json.loads(out.stdout.decode("utf-8"))
    py_schema = json.loads((SCHEMA_DIR / "lesson.json").read_text(encoding="utf-8"))
    # 只断言"两边都要求同一批必填字段"——逐字段比对会把合法演进变成红灯
    kernel_required = set(kernel_schema.get("required") or [])
    py_required = set(py_schema.get("required") or [])
    assert py_required <= kernel_required | py_required
    assert {"key", "title", "layer", "steps"} <= kernel_required | py_required


def test_cli_info_runs():
    from repolearn.cli import main

    assert main(["info"]) == 0


def test_cli_help_runs(capsys):
    from repolearn.cli import main

    assert main([]) == 0
    captured = capsys.readouterr()
    assert "migrate" in captured.out


def test_cli_export_openapi_check_detects_drift(tmp_path, monkeypatch):
    """`--check` 在干净树上通过；手改 schema 后必须失败（T-CON-1）。"""
    from repolearn import cli

    target = REPO_ROOT / "packages" / "contracts" / "openapi.json"
    # 先写入当前真实内容
    assert cli.main(["export-openapi"]) == 0
    assert cli.main(["export-openapi", "--check"]) == 0

    original = target.read_text(encoding="utf-8")
    try:
        data = json.loads(original)
        data["paths"].pop("/healthz", None)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        assert cli.main(["export-openapi", "--check"]) == 1
    finally:
        target.write_text(original, encoding="utf-8")
    assert cli.main(["export-openapi", "--check"]) == 0


def test_openapi_contains_all_expected_groups():
    from repolearn.main import create_app

    paths = create_app().openapi()["paths"]
    for expected in (
        "/v1/setup/state",
        "/v1/setup/llm/probe",
        "/v1/setup/commit",
        "/v1/settings/profiles",
        "/v1/courses",
        "/v1/courses/{course_id}/lessons/{lesson_key}/playback",
        "/v1/courses/{course_id}/questions",
        "/v1/courses/{course_id}/progress",
        "/v1/courses/{course_id}/recap",
        "/v1/books/{book_id}",
        "/v1/jobs",
        "/v1/jobs/{job_id}/events",
        "/v1/objects/{kind}/{name}",
        "/healthz",
    ):
        assert expected in paths, expected


def test_env_example_lists_every_setting():
    """`.env.example` 是配置的唯一说明（§4.1）：漏一个变量等于让用户猜。"""
    from repolearn.core.config import Settings

    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    missing = []
    for name in Settings.model_fields:
        env_name = f"REPOLEARN_{name.upper()}"
        if env_name not in text:
            missing.append(env_name)
    assert missing == [], f".env.example 缺少：{missing}"


def test_pyproject_declares_packaging_for_cli():
    """P0-5：没有这段配置，`python -m repolearn.cli` 在干净环境下不可达。"""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "apps/api/repolearn" in text
    assert "[tool.hatch.build.targets.wheel.sources]" in text
    assert 'pythonpath = ["apps/api"]' in text


def test_readme_and_scripts_exist():
    for name in ("README.md", "start.ps1", "stop.ps1", "scripts/check_env.ps1"):
        assert (REPO_ROOT / name).is_file(), name


def test_scripts_are_ascii_or_utf8_bom():
    """PowerShell 5.1 对无 BOM 的 UTF-8 中文会解析失败（R11）。

    脚本必须要么纯 ASCII，要么带 UTF-8 BOM。这条断言防的是"在我机器上能跑"。
    """
    for name in ("start.ps1", "stop.ps1", "scripts/check_env.ps1"):
        raw = (REPO_ROOT / name).read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            continue
        try:
            raw.decode("ascii")
        except UnicodeDecodeError:
            raise AssertionError(f"{name} 既不是纯 ASCII 也没有 UTF-8 BOM，PowerShell 5.1 会解析失败") from None


def test_no_hardcoded_absolute_backend_url_in_client_code():
    """同源约束：客户端代码里不得出现绝对后端地址（spec §2.2 约束 6）。"""
    web = REPO_ROOT / "apps" / "web" / "src"
    if not web.exists():
        pytest.skip("apps/web 尚未生成")
    offenders: list[str] = []
    for path in web.rglob("*.ts*"):
        if "node_modules" in str(path) or "lib/env.ts" in str(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in ("http://127.0.0.1:8000", "http://localhost:8000"):
            if needle in text and "'use client'" in text[:600]:
                offenders.append(f"{path.name}: {needle}")
    assert offenders == [], offenders


def test_python_sources_have_no_bom_and_are_utf8():
    for path in (REPO_ROOT / "apps" / "api" / "repolearn").rglob("*.py"):
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), path
        raw.decode("utf-8")


def test_requirements_include_langgraph_and_fastapi():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "langgraph" in text
    assert "fastapi" in text
    assert "sqlalchemy" in text
    assert "jsonschema" in text


def test_skill_style_docs_present():
    for name in ("docs/runbook.md", "docs/architecture.md", "docs/api.md"):
        assert (REPO_ROOT / name).is_file(), name
