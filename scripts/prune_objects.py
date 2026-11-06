"""对象清理：镜像 LRU + 孤儿音频/PDF + 过期幂等键（spec §4.1 / T-OPS-1）。

**只删未被引用的对象。** 这是 T-OPS-1 的核心断言：镜像与音频都可能仍被
数据库引用，误删的表现是"课程能打开，但播放器 404 / 导出的 PDF 不见了"。

    python scripts/prune_objects.py                # 只做安全清理（镜像 LRU + 幂等键）
    python scripts/prune_objects.py --orphans      # 额外清理没有数据库引用的音频/PDF
    python scripts/prune_objects.py --dry-run      # 只报告，不删
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


async def _referenced() -> tuple[set[str], set[str]]:
    """从数据库取"仍被引用"的对象 key 集合。"""
    from sqlalchemy import select

    from repolearn.core.db import session_scope
    from repolearn.models import AudioAsset, PdfExport

    async with session_scope() as session:
        audio = {row.object_key for row in (await session.execute(select(AudioAsset))).scalars().all() if row.object_key}
        pdf = {row.object_key for row in (await session.execute(select(PdfExport))).scalars().all() if row.object_key}
    return audio, pdf


async def _prune_idempotency() -> int:
    from sqlalchemy import delete

    from repolearn.core.clock import utcnow
    from repolearn.core.db import session_scope
    from repolearn.models import IdempotencyKey

    async with session_scope() as session:
        cutoff = utcnow() - timedelta(minutes=10)
        result = await session.execute(delete(IdempotencyKey).where(IdempotencyKey.expires_at < cutoff))
        return int(result.rowcount or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 RepoLearn 的对象存储")
    parser.add_argument("--orphans", action="store_true", help="同时清理没有数据库引用的音频/PDF")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不删除")
    parser.add_argument("--max-mirror-gb", type=float, default=2.0, help="镜像总量上限（GB）")
    args = parser.parse_args()

    from repolearn.services import object_store

    loop = asyncio.get_event_loop_policy().new_event_loop()
    audio_refs, pdf_refs = loop.run_until_complete(_referenced())

    mirrors = object_store.list_keys("mirrors")
    audio_keys = object_store.list_keys("audio")
    pdf_keys = object_store.list_keys("pdf")

    print(f"mirrors: {len(mirrors)} entries")
    print(f"audio:   {len(audio_keys)} files, {len(audio_refs)} referenced")
    print(f"pdf:     {len(pdf_keys)} files, {len(pdf_refs)} referenced")

    orphan_audio = [k for k in audio_keys if k not in audio_refs]
    orphan_pdf = [k for k in pdf_keys if k not in pdf_refs]
    print(f"orphans: audio={len(orphan_audio)} pdf={len(orphan_pdf)}")

    if args.dry_run:
        print("[dry-run] no changes made")
        return 0

    if args.orphans:
        for key in orphan_audio:
            object_store.remove("audio", key)
        for key in orphan_pdf:
            object_store.remove("pdf", key)
        print(f"removed {len(orphan_audio) + len(orphan_pdf)} orphan object(s)")

    result = object_store.prune_mirrors(int(args.max_mirror_gb * 1024 * 1024 * 1024))
    print(f"mirror LRU: removed {result['removed_dirs']} dirs / {result['removed_bytes']} bytes")

    removed = loop.run_until_complete(_prune_idempotency())
    print(f"idempotency keys: removed {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
