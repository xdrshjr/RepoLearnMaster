"""从 ORM 元数据生成 `0001_initial.py`（作者工具，不是运行时依赖）。

为什么用生成而不是手写：26 张表手写 DDL 必然与模型分叉，而"迁移和模型不一致"
是这类项目最难查的一类 bug（模型能插入、迁移建的表少一列）。生成出来的文件是
**冻结的历史**：之后所有结构变更都必须另开迁移文件，不得再跑这个脚本覆盖它。

正常运行方式（仅当需要重建初始迁移，例如从零重写项目时）：

    .venv\\Scripts\\python.exe scripts/gen_migration.py

⚠️ 它会**覆盖** `apps/api/migrations/versions/0001_initial.py`。日常开发不要跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.sql.schema import Column  # noqa: E402

from repolearn.core.db import Base  # noqa: E402
from repolearn.models import ALL_MODELS  # noqa: E402,F401  —— 注册全部表
from repolearn.models._types import UtcDateTime  # noqa: E402

OUT = ROOT / "apps" / "api" / "migrations" / "versions" / "0001_initial.py"


def render_type(col: Column) -> str:
    t = col.type
    if isinstance(t, UtcDateTime):
        return "sa.DateTime()"
    if isinstance(t, sa.JSON):
        return "JSON_T"
    if isinstance(t, sa.Text):
        return "sa.Text()"
    if isinstance(t, sa.String):
        return f"sa.String({t.length})" if t.length else "sa.String()"
    if isinstance(t, sa.Boolean):
        return "sa.Boolean()"
    if isinstance(t, sa.Integer):
        return "sa.Integer()"
    if isinstance(t, sa.Float):
        return "sa.Float()"
    if isinstance(t, sa.LargeBinary):
        return "sa.LargeBinary()"
    if isinstance(t, sa.DateTime):
        return "sa.DateTime()"
    raise SystemExit(f"未映射的列类型 {t!r} on {col}")


def render_column(col: Column) -> str:
    parts = [f'"{col.name}"', render_type(col)]
    for fk in sorted(col.foreign_keys, key=lambda f: f.target_fullname):
        if fk.constraint and fk.constraint.ondelete:
            parts.append(f'sa.ForeignKey("{fk.target_fullname}", ondelete="{fk.constraint.ondelete}")')
        else:
            parts.append(f'sa.ForeignKey("{fk.target_fullname}")')
    if col.primary_key:
        parts.append("primary_key=True")
    if not col.nullable:
        parts.append("nullable=False")
    return f"sa.Column({', '.join(parts)})"


def render_table(table: sa.Table) -> str:
    lines = ["    op.create_table(", f'        "{table.name}",']
    for col in table.columns:
        lines.append(f"        {render_column(col)},")
    for c in table.constraints:
        if isinstance(c, sa.UniqueConstraint) and c.name:
            cols = ", ".join(f'"{col.name}"' for col in c.columns)
            lines.append(f'        sa.UniqueConstraint({cols}, name="{c.name}"),')
    lines.append("    )")
    stmts = ["\n".join(lines)]
    for idx in sorted(table.indexes, key=lambda i: i.name or ""):
        if idx.name is None:
            continue
        cols = ", ".join(f'"{col.name}"' for col in idx.columns)
        extra = ", unique=True" if idx.unique else ""
        stmts.append(f'    op.create_index("{idx.name}", "{table.name}", [{cols}]{extra})')
    return "\n".join(stmts)


PARTIAL_UP = "CREATE UNIQUE INDEX ux_llm_profiles_active ON llm_profiles (active) WHERE active = 1"
PARTIAL_DOWN = "DROP INDEX IF EXISTS ux_llm_profiles_active"


def main() -> None:
    tables = list(Base.metadata.sorted_tables)
    blocks = [render_table(t) for t in tables]
    header = '''"""0001_initial —— 一次建全表（spec §6.2 的 26 张表 + 索引 + 唯一约束）。

由 `scripts/gen_migration.py` 从 ORM 元数据生成，**之后冻结**：任何结构变更都必须
新增迁移文件，不得修改本文件（T-DB-1 的 upgrade→downgrade→upgrade 往返依赖它
作为稳定基线）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

#: JSON 在 SQLite 存 TEXT，在 PG 存 JSONB（spec §6.7）
JSON_T = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
'''
    drops = []
    for t in reversed(tables):
        for idx in sorted(t.indexes, key=lambda i: i.name or ""):
            if idx.name:
                drops.append(f'    op.drop_index("{idx.name}", table_name="{t.name}")')
        drops.append(f'    op.drop_table("{t.name}")')
    text = (
        header
        + "\n\n".join(blocks)
        + "\n\n    # 部分唯一索引：不能同时存在两个 active profile（T-DB-3）。\n"
        + f'    op.execute("{PARTIAL_UP}")\n'
        + "\n\ndef downgrade() -> None:\n"
        + f'    op.execute("{PARTIAL_DOWN}")\n'
        + "\n".join(drops)
        + "\n"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text)} bytes, {len(tables)} tables)")


if __name__ == "__main__":
    main()
