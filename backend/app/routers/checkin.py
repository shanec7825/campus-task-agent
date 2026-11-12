"""签到路由（契约 `C-TASKS@1` #11/#12，owner = T2）。

规则（R4，按 `C-APPLY@1` 多负责人模型升级）：
- 仅任务 approved 成员可签到（``4030``，``is_approved_participant`` 含 legacy 回退）；
- 任务不存在 ``4040``；
- 同一用户同一任务只能签到一次，重复 ``4090``（数据库 ``UNIQUE(task_id, user_id)`` 兜底）；
  多名 approved 成员各可签到一次；
- 签到成功后给任务发布者写一条 ``info`` 通知（唯一写通知入口 = ``notify_service``）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import ApiError, ok
from app.models import Checkin, Task, User
from app.routers.tasks import (
    ERR_CONFLICT,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
)
from app.schemas import CheckinIn, CheckinOut
from app.services import application_service, notify_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checkin", tags=["checkin"])


def _now_local() -> str:
    """服务器本地时间，格式与全库口径一致：``YYYY-MM-DD HH:MM:SS``。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _checkin_payload(checkin: Checkin, task_title: str | None) -> dict[str, Any]:
    """构造与 ``CheckinOut`` 对齐的字典。"""
    return CheckinOut.model_validate(
        {
            "id": checkin.id,
            "task_id": checkin.task_id,
            "user_id": checkin.user_id,
            "task_title": task_title,
            "checkin_time": checkin.checkin_time,
        }
    ).model_dump()


@router.post("")
def checkin(
    payload: CheckinIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """对本任务签到（每人每任务一次）。"""
    task = db.get(Task, payload.task_id)
    if task is None:
        raise ApiError(ERR_NOT_FOUND, "任务不存在")
    # 多名 approved 成员均可签到（含 legacy 回退）；assignee_id 判空逻辑已删除
    if not application_service.is_approved_participant(db, task, int(current_user.id)):
        raise ApiError(ERR_FORBIDDEN, "只有任务成员可以签到")

    exists = (
        db.query(Checkin)
        .filter(Checkin.task_id == task.id, Checkin.user_id == current_user.id)
        .first()
    )
    if exists is not None:
        raise ApiError(ERR_CONFLICT, "该任务已签到，请勿重复签到")

    record = Checkin(task_id=task.id, user_id=current_user.id, checkin_time=_now_local())
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # 并发重复签到：唯一约束兜底，语义与前置检查一致
        db.rollback()
        raise ApiError(ERR_CONFLICT, "该任务已签到，请勿重复签到")
    db.refresh(record)

    data = _checkin_payload(record, task.title)

    notify_service.create_notification(
        db,
        user_id=task.publisher_id,
        task_id=task.id,
        level="info",
        title="成员已签到",
        content=f"{current_user.display_name} 已签到《{task.title}》。",
    )
    return ok(data)


@router.get("/me")
def my_checkins(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """当前用户的全部签到记录（含``task_title``），按 ``checkin_time DESC``。"""
    records = (
        db.query(Checkin)
        .filter(Checkin.user_id == current_user.id)
        .order_by(Checkin.checkin_time.desc(), Checkin.id.desc())
        .all()
    )

    task_ids = {int(record.task_id) for record in records}
    titles: dict[int, str] = {}
    if task_ids:
        rows = db.query(Task.id, Task.title).filter(Task.id.in_(task_ids)).all()
        titles = {int(row[0]): str(row[1]) for row in rows}

    items = [_checkin_payload(record, titles.get(int(record.task_id))) for record in records]
    return ok({"items": items})


__all__ = ["router"]