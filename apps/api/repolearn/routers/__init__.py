"""Router 注册表。顺序不重要（路径不重叠），但分组要清楚。"""

from __future__ import annotations

from fastapi import APIRouter

from repolearn.routers import (
    books,
    courses,
    health,
    jobs,
    lessons,
    notes,
    objects,
    playback,
    progress,
    questions,
    repos,
    settings,
    setup,
)

ALL_ROUTERS: tuple[APIRouter, ...] = (
    health.router,
    setup.router,
    settings.router,
    repos.router,
    courses.router,
    lessons.router,
    playback.router,
    questions.router,
    progress.router,
    notes.router,
    books.router,
    jobs.router,
    objects.router,
)

__all__ = ["ALL_ROUTERS"]
