"""任务状态机（契约 `C-MEMBER@1`，owner = T2）。

:data:`ALLOWED_TRANSITIONS` 是全后端**唯一**的合法流转集合：``routers/tasks.py``
的写库前校验与 :func:`app.services.member_service.sync_task_status` 的聚合状态
重算共用本表，禁止在别处另写一份集合。

``overdue`` 是非终态：成员提交 / 验收 / 发布者改期之后，聚合状态可回到
``claimed`` / ``in_progress`` / ``submitted`` / ``verified``（R4）。
``verified`` / ``cancelled`` 为终态，任何聚合都不再流转。
"""

from __future__ import annotations

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "published": frozenset({"claimed", "cancelled", "overdue"}),
    "claimed": frozenset({"in_progress", "cancelled", "overdue"}),
    "in_progress": frozenset({"submitted", "cancelled", "overdue"}),
    "submitted": frozenset({"verified", "in_progress", "cancelled", "overdue"}),
    "overdue": frozenset({"claimed", "in_progress", "submitted", "verified", "cancelled"}),
    "verified": frozenset(),
    "cancelled": frozenset(),
}


def is_allowed(current: str, target: str) -> bool:
    """判断 ``current -> target`` 是否在合法流转集合内。"""
    return target in ALLOWED_TRANSITIONS.get(str(current), frozenset())


__all__ = ["ALLOWED_TRANSITIONS", "is_allowed"]