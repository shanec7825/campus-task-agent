"""资料库路由（契约 `C-RESOURCE@1`）。

* ``GET /api/resources``：权限内检索（关键词、活动、任务、任务相关资料）；
* ``POST /api/resources``：新增资料或为同一 ``resource_key`` 追加新版本。

可见性过滤与归属校验全部在 ``services.resource_service`` 内完成，路由不另写权限判断。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf
from app.errors import ok
from app.models import User
from app.schemas import ResourceCreateIn
from app.services import resource_service

router = APIRouter(
    prefix="/api/resources", tags=["resources"], dependencies=[Depends(require_csrf)]
)

MAX_QUERY_LENGTH = 500


@router.get("")
def list_resources(
    q: str = Query(default="", max_length=MAX_QUERY_LENGTH),
    activity_id: int | None = Query(default=None),
    task_id: int | None = Query(default=None),
    related_task_id: int | None = Query(default=None),
    limit: int = Query(default=resource_service.DEFAULT_LIMIT, ge=1, le=resource_service.MAX_LIMIT),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """按当前用户权限检索资料；结果只含可见条目。"""
    items = resource_service.list_resources(
        db,
        current_user,
        query=q,
        activity_id=activity_id,
        task_id=task_id,
        related_task_id=related_task_id,
        limit=limit,
    )
    return ok({"items": [item.model_dump() for item in items], "total": len(items)})


@router.post("")
def create_resource(
    payload: ResourceCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """新增资料或追加版本；返回写入后的完整条目。"""
    row = resource_service.create_resource(db, current_user, payload)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return ok(resource_service.to_out(db, [row])[0].model_dump())


__all__ = ["router"]