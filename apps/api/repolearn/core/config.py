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

from pydantic import Field, field_validator
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

    kernel_url: str = "http://127.0.0.1:8787"
    agent_runtime: str = "auto"

    max_concurrent_jobs: int = 1
    job_deadline_ms: int = 1_500_000
    job_max_tokens: int = 180_000
    job_max_usd: float = 0.35
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
    def run_dir(self) -> Path:
        return REPO_ROOT / ".run"

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
            self.run_dir,
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
