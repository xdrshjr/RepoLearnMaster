"""应用配置。

全部配置来自 `REPOLEARN_*` 环境变量（或仓库根的 `.env`）。这里是唯一读取
环境变量的地方：其他模块一律 `from repolearn.core.config import settings`，
这样"配置从哪里来"永远只有一个答案，测试也可以整体替换。
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]

#: 进程内兜底密钥。`REPOLEARN_SECRET_KEY` 为空时才用，且**只生成一次**：
#: 只要它每次都变，加密与解密就不可能对上（见 `Settings.fernet_key`）。
_EPHEMERAL_KEY: bytes | None = None


def _ephemeral_key() -> bytes:
    global _EPHEMERAL_KEY
    if _EPHEMERAL_KEY is None:
        _EPHEMERAL_KEY = hashlib.sha256(os.urandom(32)).digest()
        import logging

        logging.getLogger("repolearn.config").warning(
            "REPOLEARN_SECRET_KEY 未配置：API Key 使用进程内临时密钥加密，重启后需要重新填写。"
        )
    return _EPHEMERAL_KEY


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REPOLEARN_",
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    web_port: int = 3000
    api_port: int = 8000
    kernel_port: int = 8787

    database_url: str = "sqlite+aiosqlite:///./var/data/repolearn.db"
    checkpoint_db: str = "./var/data/langgraph.sqlite"
    object_root: str = "./var/objects"

    secret_key: str = ""
    secret_key_previous: str = ""
    internal_token: str = ""

    github_token: str = ""
    max_repo_mb: int = 60
    # GitHub 接入点（hardening spec §3.2.1）。默认值就是官方站点，因此既有行为
    # 在"什么都不配"时逐字节不变；改成自建 GHE / 本地假端点时才生效。
    # **只允许来自服务端环境变量**：任何请求体/查询参数都不得覆盖它，否则
    # `POST /v1/courses {api_base: "http://169.254.169.254"}` 就是一个 SSRF 洞。
    github_api_base: str = "https://api.github.com"
    github_web_base: str = "https://github.com"

    # 运行时状态目录（hardening spec P1-5）。环境变量就是 `REPOLEARN_RUN_DIR`。
    # `preflight.json` / `ports.json` / pid 文件全是**跟运行实例走**的事实；写死在
    # `REPO_ROOT/.run` 会让 e2e-real 读到开发机上一次运行的旧结论，然后用旧事实
    # 解释新行为。字段本身是字符串（与环境变量同形），Path 由 `run_path` 派生。
    run_dir: str = ""

    kernel_url: str = "http://127.0.0.1:8787"
    agent_runtime: str = "auto"

    max_concurrent_jobs: int = 1
    job_deadline_ms: int = 1_500_000
    #: Job 级 token 总闸。2026-11-09 从 180_000 放宽到 2_000_000：v1 的
    #: `plan_curriculum` 节点分闸只有 20k，真实仓库单次规划就用到 30k+，
    #: 课程在 N5 就 `failed_budget`。两档一起放宽后，"跑一门课"不再因为
    #: 预算而在中段死掉；要收紧时改这里（或 `REPOLEARN_JOB_MAX_TOKENS`）。
    job_max_tokens: int = 2_000_000
    job_max_usd: float = 50.0
    heartbeat_seconds: int = 15
    job_stale_seconds: int = 90

    search: str = "scan"
    vision_qa: bool = False
    pdf_default_engine: str = "chromium"

    doubao_app_id: str = ""
    doubao_access_token: str = ""
    doubao_cluster: str = "volcano_tts"
    doubao_voice_type: str = "zh_female_wanwanxiaohe_moon_bigtts"

    api_base: str = "http://127.0.0.1:8000"
    web_mock: bool = False

    # 出站 HTTP 的默认超时（连接, 读取），spec §3.11.3
    http_timeout_connect: float = 5.0
    http_timeout_read: float = 60.0

    # 发布门禁（spec §3.4）
    min_lessons_to_publish: int = 8
    min_anchor_coverage: float = 0.8
    min_sections_to_publish: int = 4

    @field_validator("agent_runtime")
    @classmethod
    def _check_runtime(cls, v: str) -> str:
        allowed = {"kernel", "exec", "template", "auto"}
        if v not in allowed:
            raise ValueError(f"REPOLEARN_AGENT_RUNTIME must be one of {sorted(allowed)}")
        return v

    @field_validator("search")
    @classmethod
    def _check_search(cls, v: str) -> str:
        if v not in {"scan", "fts"}:
            raise ValueError("REPOLEARN_SEARCH must be 'scan' or 'fts'")
        return v

    @field_validator("github_api_base", "github_web_base")
    @classmethod
    def _check_http_url(cls, v: str) -> str:
        """两个 base 必须是 http(s) URL 且不带尾部斜杠。

        校验放在配置层而不是使用处：一个拼错的端点只会在"第一次点生成"时暴露，
        而那时代价是用户等了 30 秒才看到一个 503。启动时就炸，比运行时炸好。
        """
        v = (v or "").strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("REPOLEARN_GITHUB_API_BASE / REPOLEARN_GITHUB_WEB_BASE 必须是 http(s) URL")
        return v

    @field_validator("run_dir")
    @classmethod
    def _check_relaxed_path(cls, v: str) -> str:
        return (v or "").strip()

    # ---- 派生路径 ---------------------------------------------------------
    @property
    def repo_root(self) -> Path:
        return REPO_ROOT

    @property
    def var_dir(self) -> Path:
        return REPO_ROOT / "var"

    @property
    def object_path(self) -> Path:
        p = Path(self.object_root)
        return p if p.is_absolute() else (REPO_ROOT / p)

    @property
    def log_dir(self) -> Path:
        return self.var_dir / "logs"

    @property
    def run_path(self) -> Path:
        """运行时状态目录的**物理路径**。默认 `REPO_ROOT/.run`，可由 `REPOLEARN_RUN_DIR` 覆盖。

        覆盖是**修正**而不是新增能力：里面的 `preflight.json` / `ports.json` /
        pid 文件本来就是运行时状态，固定路径会让并行跑的两份工作区互相覆盖，
        也会让 e2e-real 把开发机的旧 Gate 0 结论当成这一轮的结论。
        """
        raw = (self.run_dir or "").strip()
        if not raw:
            return REPO_ROOT / ".run"
        p = Path(raw)
        return p if p.is_absolute() else (REPO_ROOT / p)

    @property
    def github_api(self) -> str:
        return self.github_api_base.rstrip("/")

    @property
    def github_web(self) -> str:
        return self.github_web_base.rstrip("/")

    @property
    def github_allowed_hosts(self) -> frozenset[str]:
        """允许出现在出站流量里的 host 集合（含官方站点）。

        官方站点永远在白名单里：既有用例都用 `https://github.com/...`，把它们
        一起禁掉会让"配了自建端点"变成"官方仓库不能导入了"。
        """
        from urllib.parse import urlparse

        hosts = {"github.com", "www.github.com", "api.github.com", "codeload.github.com"}
        for raw in (self.github_web, self.github_api):
            netloc = urlparse(raw).netloc.lower()
            if netloc:
                hosts.add(netloc)
        return frozenset(hosts)

    @property
    def sqlite_path(self) -> Path | None:
        """业务库的物理路径；非 SQLite 时返回 None。"""
        url = self.database_url
        if "sqlite" not in url:
            return None
        raw = url.split("///", 1)[-1]
        if not raw or raw == ":memory:":
            return None
        p = Path(raw)
        return p if p.is_absolute() else (REPO_ROOT / p)

    @property
    def resolved_database_url(self) -> str:
        """把相对 SQLite 路径固定到仓库根。

        不这么做的话，`alembic upgrade`（从仓库根跑）与 `uvicorn`（从 apps/api 跑）
        会打开**两个不同的数据库文件**，而症状是"迁移明明跑了，表却不存在"。
        """
        url = self.database_url
        if "sqlite" not in url:
            return url
        path = self.sqlite_path
        if path is None:
            return url
        path.parent.mkdir(parents=True, exist_ok=True)
        prefix = url.split("///", 1)[0]
        return f"{prefix}///{path.as_posix()}"

    def ensure_dirs(self) -> None:
        for d in (
            self.var_dir / "data",
            self.object_path,
            self.object_path / "mirrors",
            self.object_path / "audio",
            self.object_path / "pdf",
            self.object_path / "diagrams",
            self.object_path / "artifacts",
            self.log_dir,
            self.run_path,
            REPO_ROOT / "var" / "uploads",
        ):
            d.mkdir(parents=True, exist_ok=True)

    # ---- 密钥 -------------------------------------------------------------
    @property
    def fernet_key(self) -> bytes:
        """把 `secret_key` 归一化为 32 字节 AES-GCM 密钥。

        接受 urlsafe base64 的 32 字节（Fernet 形态），也接受任意口令
        （用 sha256 派生），因为"开发机第一跑不想手工造密钥"是硬要求。

        没有配置密钥时用一个**进程内固定**的随机值兜底：每次调用都重新随机
        会让"加密时用的 key"和"解密时用的 key"永远不同，库里只会留下一堆
        谁也解不开的密文，而且症状是"模型调用静默失效"而不是报错。
        """
        raw = (self.secret_key or "").strip()
        if raw:
            try:
                decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
                if len(decoded) == 32:
                    return decoded
            except Exception:  # noqa: BLE001 - 任意非法 base64 都走口令派生
                pass
            return hashlib.sha256(raw.encode("utf-8")).digest()
        return _ephemeral_key()

    @property
    def has_secret_key(self) -> bool:
        return bool((self.secret_key or "").strip())

    def generate_missing_secrets(self) -> dict[str, str]:
        """返回应写回 `.env` 的缺失密钥（start.ps1 首次运行时调用）。"""
        created: dict[str, str] = {}
        if not self.secret_key:
            created["REPOLEARN_SECRET_KEY"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        if not self.internal_token:
            created["REPOLEARN_INTERNAL_TOKEN"] = secrets.token_urlsafe(24)
        return created


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()
