"""镜像快照的纯函数差分与升级计划（hardening spec §3.5.1）。

**不用 git**：我们手里只有两份解包后的镜像，而且产品边界明确规定"不执行任何
仓库代码/命令"。因此内容哈希是唯一可靠的比对依据——`git diff` 需要仓库历史，
而我们连 `.git` 都被路径守卫挡在镜像之外。

**不做函数级 diff**：tree-sitter 双版本符号树比对能少重建 1–2 个课时，代价是
漏判时要交付"讲解与代码不一致"的课程——而一致性是本产品的核心承诺。文件级
diff 的误差方向是"多重建几个课时"，代价可接受（spec §10 第 1 条）。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Status = Literal["added", "modified", "removed"]

#: 受影响课时占比超过它就直接全量（spec §3.5.1 第 3 条）。
#: 经验值：超过六成时"复制省下的工作量"已经小于"合并两份大纲的成本"。
FULL_REBUILD_RATIO = 0.6

#: 新增文件占比阈值（第 4 条）。新文件通常意味着新模块/新入口，大纲要重排；
#: 只补课时会得到"大纲里没有的那一半代码"。
NEW_FILES_RATIO = 0.10

#: 新增文件的绝对下限：占比在极小仓库上会退化成"改一个文件就全量"。
NEW_FILES_MIN = 3


@dataclass(frozen=True)
class FileDelta:
    path: str
    status: Status
    old_sha: str | None = None
    new_sha: str | None = None


@dataclass(frozen=True)
class LessonRef:
    """一门课里"某个课时引用了哪些文件"的最小投影。

    `files` 的取值来源是 `anchors ∪ steps.focus_file ∪ code_notes.file ∪
    playback_meta.files`——四者任意一处引用了文件，这个文件变了就该重讲这一课。
    少算一处的结果是"用户看着旧讲解读新代码"，比多讲一遍糟得多。
    """

    key: str
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpgradePlan:
    mode: Literal["none", "partial", "full"]
    affected_keys: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    stats: dict[str, int] | None = None

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "affected_keys": list(self.affected_keys),
            "reasons": list(self.reasons),
            "stats": dict(self.stats or {}),
        }


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(256 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_index(root: Path) -> dict[str, str]:
    """`{相对路径: sha256}`。路径统一成 `/` 分隔，与镜像清单同一口径。"""
    root = Path(root)
    index: dict[str, str] = {}
    if not root.is_dir():
        return index
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        index[rel] = _digest(path)
    return index


def diff_snapshots(old_root: Path, new_root: Path) -> list[FileDelta]:
    """两份镜像的内容差分。结果按路径升序，因此是**确定性**的。

    确定性不是为了好看：`T-UPG-2` 要拿它跟夹具的期望形状逐条比对，而"顺序
    随机"会让这条断言时红时绿。
    """
    old = snapshot_index(old_root)
    new = snapshot_index(new_root)
    deltas: list[FileDelta] = []
    for path in sorted(set(old) | set(new)):
        old_sha = old.get(path)
        new_sha = new.get(path)
        if old_sha is None:
            deltas.append(FileDelta(path=path, status="added", new_sha=new_sha))
        elif new_sha is None:
            deltas.append(FileDelta(path=path, status="removed", old_sha=old_sha))
        elif old_sha != new_sha:
            deltas.append(FileDelta(path=path, status="modified", old_sha=old_sha, new_sha=new_sha))
    return deltas


def changed_paths(deltas: Sequence[FileDelta]) -> set[str]:
    return {d.path for d in deltas}


def plan_upgrade(
    lessons: Sequence[LessonRef],
    deltas: Sequence[FileDelta],
    *,
    total_files: int,
    old_mirror_ok: bool = True,
) -> UpgradePlan:
    """判定顺序**命中即返回**，顺序本身就是语义（spec §3.5.1）。

    `total_files` 的定义被钉死为"**旧镜像中被 analysis 收录、并计入
    `Commit.file_count` 的可分析文件数**"（不含 .md/图片/二进制/被路径守卫跳过
    的文件）。理由：第 4 条问的是"新代码占比是否大到要重排大纲"，被跳过的文件
    从来不进大纲，把它们算进分母只会让阈值失效。分母口径不定死，同一份 delta
    在开发机上判 partial、在 CI 上判 full，而两边都"有测试"。
    """
    stats = {
        "files_added": sum(1 for d in deltas if d.status == "added"),
        "files_modified": sum(1 for d in deltas if d.status == "modified"),
        "files_removed": sum(1 for d in deltas if d.status == "removed"),
        "lessons_total": len(lessons),
        "total_files": int(total_files),
    }

    # 1. 旧镜像被 LRU 清掉 → 无法判断"哪些没变"，只能全量。
    if not old_mirror_ok:
        return UpgradePlan(mode="full", reasons=("old_mirror_missing",), stats=stats)

    touched = changed_paths(deltas)
    affected = sorted(
        lesson.key for lesson in lessons if touched & set(lesson.files)
    )
    stats["lessons_affected"] = len(affected)

    # 2. 没有受影响课时 → `none`，**不是** partial。没有课时要重讲却建一个新版本，
    #    等于凭空多一门课、多一次发布、多一份数据；用户点"检查更新"会得到一个
    #    与旧版逐字节相同的"新版本"。
    if not affected:
        return UpgradePlan(mode="none", reasons=("no_changes",), stats=stats)

    total_lessons = max(1, len(lessons))
    ratio = len(affected) / total_lessons
    if ratio > FULL_REBUILD_RATIO:
        return UpgradePlan(
            mode="full",
            reasons=(f"curriculum_shift:{len(affected)}/{total_lessons}",),
            stats=stats,
        )

    denominator = max(1, int(total_files))
    new_file_threshold = max(NEW_FILES_MIN, math.ceil(denominator * NEW_FILES_RATIO))
    if stats["files_added"] >= new_file_threshold:
        return UpgradePlan(
            mode="full",
            reasons=(f"many_new_files:{stats['files_added']}>={new_file_threshold}",),
            stats=stats,
        )

    reasons = (
        f"{len(deltas)} files changed, {len(affected)} lessons affected",
        f"thresholds: ratio<={FULL_REBUILD_RATIO}, new_files<{new_file_threshold}",
    )
    return UpgradePlan(mode="partial", affected_keys=tuple(affected), reasons=reasons, stats=stats)


def lesson_files_from_rows(
    lessons: Sequence,
    steps: Sequence,
    anchors: Sequence,
) -> list[LessonRef]:
    """把 ORM 行投影成 `LessonRef`（四个来源的并集，见 `LessonRef` 的注释）。

    放在这里而不是 service 里，是为了让"哪些字段算引用"这件事只有一处定义；
    换版本时若漏掉 `code_notes.file`，用户就会看到"注释指向新代码、讲解讲的是旧
    逻辑"——这类不一致不会被任何页面报错，只会被用户发现。
    """
    by_lesson: dict[str, set[str]] = {}
    for lesson in lessons:
        by_lesson.setdefault(lesson.id, set())
        for item in (lesson.playback_meta or {}).get("files") or []:
            if isinstance(item, dict) and item.get("path"):
                by_lesson[lesson.id].add(str(item["path"]))
    for step in steps:
        bucket = by_lesson.setdefault(step.lesson_id, set())
        if step.focus_file:
            bucket.add(str(step.focus_file))
        for note in step.code_notes or []:
            if isinstance(note, dict) and note.get("file"):
                bucket.add(str(note["file"]))
        for seg in step.segments or []:
            focus = (seg or {}).get("focus") if isinstance(seg, dict) else None
            if isinstance(focus, dict) and focus.get("file"):
                bucket.add(str(focus["file"]))
    for anchor in anchors:
        if anchor.lesson_id:
            by_lesson.setdefault(anchor.lesson_id, set()).add(str(anchor.file))
    return [
        LessonRef(key=lesson.key, files=tuple(sorted(by_lesson.get(lesson.id, set()))))
        for lesson in lessons
    ]


__all__ = [
    "FULL_REBUILD_RATIO",
    "NEW_FILES_MIN",
    "NEW_FILES_RATIO",
    "FileDelta",
    "LessonRef",
    "Status",
    "UpgradePlan",
    "changed_paths",
    "diff_snapshots",
    "lesson_files_from_rows",
    "plan_upgrade",
    "snapshot_index",
]
