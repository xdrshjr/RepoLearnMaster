"""设置服务薄封装。

历史原因：`setup_service` 同时承担"首启向导"与"设置页"两组职责，因为它们的
数据模型是同一套（profile + revision）。这个模块只把设置页用到的那几个函数
显式列出来，避免 router 直接 import 一个名字里有 "setup" 的模块——
可读性问题，不是技术问题。
"""

from __future__ import annotations

from repolearn.services.setup_service import (
    activate_profile,
    active_profile,
    doctor,
    list_profiles,
    list_revisions,
    patch_roles,
    profile_llm_configs,
    rollback,
    rotate_secret,
)

__all__ = [
    "activate_profile",
    "active_profile",
    "doctor",
    "list_profiles",
    "list_revisions",
    "patch_roles",
    "profile_llm_configs",
    "rollback",
    "rotate_secret",
]
