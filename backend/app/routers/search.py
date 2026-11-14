"""「我的活动 / 任务」搜索聚合端点（契约 `C-MY-SEARCH@1`，设计 §9.3）。

只读、无写请求，因此不加 CSRF 依赖。顺序固定：先复用既有 ``scope=mine`` 条件
（含 ``authz.visible_*_filter``）取可见集合，再按标题包含匹配，最后分页；
不扩到全组织、资料或聊天全文，也不返回组织内非 mine 对象。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import ok
from app.models import Activity, Task, User
from app.routers.activities import (
    _activity_payload,
    _mine_activity_condition,
    _visible_activity_condition,
)
from app.routers.tasks import (
    _activity_titles_map,
    _dep_status_map,
    _my_member_status,
    _my_status_map,
    _names_map,
    _task_payload,
)
from app.schemas import ActivityOut, TaskOut
from app.services import application_service, authz, member_service

router = APIRouter(prefix="/api/search", tags=["search"])

MAX_QUERY_LENGTH = 100
DEFAULT_LIMIT = 5
MAX_LIMIT = 20


def _empty_result() -> dict[str, Any]:
    return {
        "activities": {"items": [], "total": 0},
        "tasks": {"items": [], "total": 0},
    }


def _title_contains(column, keyword: str):
    """标题大小写不敏感包含匹配（参数化，``%`` / ``_`` 按字面量处理）。"""
    return func.lower(column).contains(keyword.lower(), autoescape=True)


@router.get("/mine")
def search_mine(
    q: str = Query(default="", max_length=MAX_QUERY_LENGTH),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """搜索当前用户的可见活动与任务，结果分 ``activities`` / ``tasks`` 两组。"""
    keyword = (q or "").strip()
    if not keyword:
        # 空词直接返回空组：不报错，也不允许退化成全表查询。
        return ok(_empty_result())

    visible_tasks = authz.visible_task_filter(db, current_user)

    activity_condition = and_(
        _visible_activity_condition(db, current_user, visible_tasks),
        _mine_activity_condition(db, current_user, visible_tasks),
    )
    activity_query = (
        db.query(Activity)
        .filter(activity_condition)
        .filter(_title_contains(Activity.title, keyword))
    )
    activity_total = activity_query.count()
    activity_rows = (
        activity_query.order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(limit)
        .all()
    )
    activities = [
        ActivityOut.model_validate(_activity_payload(db, row)).model_dump()
        for row in activity_rows
    ]

    task_query = (
        db.query(Task)
        .filter(
            authz.visible_task_filter(db, current_user),
            authz.my_task_condition(db, current_user),
            _title_contains(Task.title, keyword),
        )
    )
    task_total = task_query.count()
    task_rows = (
        task_query.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit).all()
    )

    # 与任务列表一致的批量派生，避免逐行查库；结果结构与 TaskOut 完全对齐。
    names = _names_map(db, task_rows)
    dep_status = _dep_status_map(db, task_rows)
    approved_names = application_service.approved_users_bulk(db, task_rows)
    counts = application_service.status_counts_bulk(db, task_rows)
    my_status = _my_status_map(db, task_rows, int(current_user.id), approved_names)
    members_by_task = member_service.members_payload_bulk(db, task_rows)
    activity_titles = _activity_titles_map(db, task_rows)
    tasks = []
    for task in task_rows:
        members = members_by_task.get(int(task.id), [])
        tasks.append(
            TaskOut.model_validate(
                _task_payload(
                    task,
                    names,
                    dep_status,
                    int(current_user.id),
                    approved_names=approved_names,
                    counts=counts.get(int(task.id), {}),
                    my_status=my_status.get(int(task.id)),
                    members=members,
                    my_member_status=_my_member_status(members, int(current_user.id)),
                    activity_titles=activity_titles,
                )
            ).model_dump()
        )

    return ok(
        {
            "activities": {"items": activities, "total": activity_total},
            "tasks": {"items": tasks, "total": task_total},
        }
    )


__all__ = ["router"]