"""回填历史课程的质量报告（spec §4.1）。

用途：`quality_report` 的口径改过之后，历史课程需要按新口径重算一次，
否则同一条课程在准备页（新口径）与列表页（旧口径）会显示不同的数字。

    python scripts/backfill_quality.py
    python scripts/backfill_quality.py --course crs_xxx
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


async def _run(course_id: str | None) -> int:
    from repolearn.core.db import session_scope
    from repolearn.services.quality_service import backfill_all, recompute

    if course_id:
        async with session_scope() as session:
            report = await recompute(session, course_id)
        print(f"recomputed {course_id}: {report}")
        return 0 if report else 1
    async with session_scope() as session:
        result = await backfill_all(session)
    print(f"backfilled {result['updated']}/{result['courses']} courses")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="回填课程质量报告")
    parser.add_argument("--course", default=None, help="只回填某一门课程")
    args = parser.parse_args()
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_run(args.course))


if __name__ == "__main__":
    raise SystemExit(main())
