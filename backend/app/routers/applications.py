"""报名与审批路由（契约 `C-APPLY@1`，owner = T2）。

本模块是**唯一**写入 ``task_applications`` 表的位置（计划 `2.3.1` 共享行为表）：
``routers/tasks.py`` 的 ``claim`` 兼容别名与 ``assign`` 均复用本模块的服务函数，
其他模块禁止直接 ``INSERT`` 该表。

对外五条接口（``APIRouter(prefix="/api")``）：

- ``POST /api/tasks/{task_id}/apply``            → A1 报名
- ``POST /api/tasks/{task_id}/apply/withdraw``   → A2 撤回
- ``GET  /api/tasks/{task_id}/applications``     → A3 发布者查看报名
- ``POST /api/applications/{application_id}/decide`` → A4 审批
- ``GET  /api/applications/me``                  → A5 我的报名

设计约束：
1. 校验顺序**严格按** ``C-APPLY@1`` 固定顺序执行，先校验后写库；
2. 每条请求最多一次业务 ``commit``；``application`` 状态、``tasks`` 字段变更与
   通知在同一事务内提交（通知用 ``commit=False`` + ``publish_committed``）；
3. 只读聚合一律走 ``services/application_service``，本模块不另写查询 SQL。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import ApiError, ok
from app.models import Task, TaskApplication, User
from app.routers import tasks as tasks_router
from app.routers.tasks import (
    ERR_CONFLICT,
    ERR_DEPENDENCY,
    ERR_FORBIDDEN,
    ERR_INVALID_PARAM,
    ERR_NOT_FOUND,
)
from app.schemas import (
    ApplicationItemOut,
    ApplicationOut,
    ApplyOut,
    DecisionIn,
    TaskBrief,
)
from app.services import application_service, member_service, notify_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["applications"])

#: 允许报名的任务状态（`C-APPLY@1` A1 第 3 条）
APPLY_ALLOWED_STATUSES: frozenset[str] = frozenset({"published", "claimed"})


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _now_local() -> str:
    """服务器本地时间，格式与全库口径一致：``YYYY-MM-DD HH:MM:SS``。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _user_names(db: Session, user_ids: list[int]) -> dict[int, str]:
    """一次 IN 查询取 ``user_id -> display_name``；缺失用户以空串兜底。"""
    ids = sorted({int(user_id) for user_id in user_ids})
    if not ids:
        return {}
    rows = db.query(User.id, User.display_name).filter(User.id.in_(ids)).all()
    return {int(row[0]): str(row[1]) for row in rows}


def _find_application(db: Session, task_id: int, user_id: int) -> TaskApplication | None:
    """按 ``UNIQUE(task_id, user_id)`` 取唯一报名行。"""
    return (
        db.query(TaskApplication)
        .filter(
            TaskApplication.task_id == int(task_id),
            TaskApplication.user_id == int(user_id),
        )
        .first()
    )


def _application_out(row: TaskApplication, user_name: str) -> ApplicationOut:
    """把报名行转换为 ``ApplicationOut``（含 ``user_name``）。"""
    return ApplicationOut(
        id=int(row.id),
        task_id=int(row.task_id),
        user_id=int(row.user_id),
        user_name=user_name,
        status=str(row.status),
        reason=row.reason,
        created_at=str(row.created_at or ""),
        decided_at=row.decided_at,
    )


def _apply_payload(
    db: Session, task: Task, row: TaskApplication, viewer_id: int
) -> dict[str, Any]:
    """构造 ``ApplyOut`` 字典：报名记录 + 最新 ``TaskOut``（含刷新后的派生字段）。"""
    names = _user_names(db, [int(row.user_id)])
    payload = ApplyOut(
        task_id=int(task.id),
        application=_application_out(row, names.get(int(row.user_id), "")),
        task=tasks_router._single_task_payload(db, task, viewer_id),
    )
    return payload.model_dump()


def _commit_or_conflict(db: Session, message: str) -> None:
    """统一提交：唯一约束 / 并发写冲突一律回滚并转 ``4090``（`C-APPLY@1` 事务边界）。"""
    try:
        db.commit()
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        notify_service.discard_pending(db)
        logger.info("报名审批写库冲突，转 4090：%s", exc)
        raise ApiError(ERR_CONFLICT, message) from exc
    except Exception:
        db.rollback()
        notify_service.discard_pending(db)
        raise
    notify_service.publish_committed(db)


def _approved_count(db: Session, task: Task) -> int:
    """该任务 approved 计数（含 legacy 回退），供名额校验与 D9 指派复用。"""
    counts = application_service.status_counts_bulk(db, [int(task.id)])
    return int(counts.get(int(task.id), {}).get(application_service.APPROVED, 0))


# --------------------------------------------------------------------------- #
# 服务函数（供 tasks.py 的 claim / assign 复用，禁止他处直接写表）
# --------------------------------------------------------------------------- #
def create_application(db: Session, task: Task, current_user: User) -> dict[str, Any]:
    """A1 / A6 共用实现：报名（含 ``claim`` 兼容别名的全部语义）。

    校验顺序严格按 `C-APPLY@1`：任务存在(4040) → 非发布者(4030) → 状态
    ``published/claimed``(4090) → 前置依赖已完成(4020) → 无 pending/approved
    记录(4090「已报名」) → 名额未满(4090) → 写 ``pending`` 并通知。

    Args:
        db: 请求级会话。
        task: 已取出的任务（调用方负责 4040；此处再兜底一次）。
        current_user: 当前登录用户。

    Returns:
        ``ApplyOut`` 字典（``application.status == "pending"``）。

    Raises:
        ApiError: 4020 / 4030 / 4040 / 4090。
    """
    # 1. 任务存在
    if task is None:
        raise ApiError(ERR_NOT_FOUND, "任务不存在")

    # 2. 不能报名自己发布的任务
    if int(task.publisher_id) == int(current_user.id):
        raise ApiError(ERR_FORBIDDEN, "不能报名自己发布的任务")

    # 3. 任务状态必须可报名
    if str(task.status) not in APPLY_ALLOWED_STATUSES:
        raise ApiError(ERR_CONFLICT, "任务当前状态不允许报名")

    # 4. 前置依赖必须已完成
    if task.depends_on is not None:
        dependency = db.get(Task, int(task.depends_on))
        if dependency is None or str(dependency.status) != "verified":
            dep_title = dependency.title if dependency is not None else "未知任务"
            raise ApiError(ERR_DEPENDENCY, f"前置任务尚未完成：《{dep_title}》")

    # 5. 同一用户已有 pending / approved 记录 ⇒ 视为已报名
    existing = _find_application(db, int(task.id), int(current_user.id))
    if (
        existing is not None
        and str(existing.status) in application_service.BLOCKING_STATUSES
    ):
        raise ApiError(ERR_CONFLICT, "已报名，请勿重复提交")

    # 6. 名额校验（quota 为 null 视为不限）
    if task.quota is not None and _approved_count(db, task) >= int(task.quota):
        raise ApiError(ERR_CONFLICT, "名额已满")

    # 7. 写库：复用 rejected / cancelled 行（UNIQUE(task_id, user_id) 不允许新增）
    now = _now_local()
    if existing is None:
        row = TaskApplication(
            task_id=int(task.id),
            user_id=int(current_user.id),
            status=application_service.PENDING,
            reason=None,
            created_at=now,
            decided_at=None,
            decided_by=None,
        )
        db.add(row)
    else:
        row = existing
        row.status = application_service.PENDING
        row.reason = None
        row.decided_at = None
        row.decided_by = None
        # 刷新报名先后（否则 approved 首位判定会落在旧时间上）
        row.created_at = now

    # 8. 通知：发布者 + 学生（同一事务内提交）
    notify_service.notify_applied(
        db,
        publisher_id=int(task.publisher_id),
        student_id=int(current_user.id),
        student_name=str(current_user.display_name),
        task_id=int(task.id),
        title=str(task.title),
        commit=False,
    )

    _commit_or_conflict(db, "已报名，请勿重复提交")
    db.refresh(row)
    return _apply_payload(db, task, row, int(current_user.id))


def approve_application_row(
    db: Session,
    task: Task,
    row: TaskApplication,
    publisher: User,
    *,
    commit: bool = True,
) -> None:
    """把 pending 报名置为 approved，并同步任务字段（D9 指派复用同一实现）。

    调用前必须已完成「名额未满」与「状态机可转移」校验；本函数只做赋值与通知，
    不做 ``commit``（``commit=True`` 时由本函数提交并推送）。

    Args:
        db: 请求级会话。
        task: 报名所属任务。
        row: 待通过的报名行（调用方保证 ``status == pending``）。
        publisher: 审批人（写入 ``decided_by``）。
        commit: 为 ``True`` 时提交并推送待推送通知。
    """
    now = _now_local()
    row.status = application_service.APPROVED
    row.reason = None
    row.decided_at = now
    row.decided_by = int(publisher.id)

    # 首位 approved 写入 assignee_id（legacy 兼容字段）
    if task.assignee_id is None:
        task.assignee_id = int(row.user_id)
    if str(task.status) == "published":
        task.status = "claimed"

    # 审批通过即建立逐人执行行（同一事务，`C-MEMBER@1`）
    member_service.ensure_member(db, task, int(row.user_id))

    notify_service.notify_decided(
        db,
        student_id=int(row.user_id),
        task_id=int(task.id),
        title=str(task.title),
        approved=True,
        commit=False,
    )
    if commit:
        _commit_or_conflict(db, "该报名已处理，请刷新后重试")


def assign_approved(
    db: Session, task: Task, target_user: User, publisher: User
) -> None:
    """D9：发布者「直接通过」某成员——有 pending 报名置 approved，无则新建 approved 行。

    调用方（``routers/tasks.py::assign_task``）负责发布者权限与任务状态校验；
    本函数负责名额二次校验、报名行写入与通知，并在结束时统一提交。

    Args:
        db: 请求级会话。
        task: 目标任务。
        target_user: 被指派的成员。
        publisher: 发布者。

    Raises:
        ApiError: ``4030``（指派自己）/ ``4090``（名额已满 / 该用户已通过报名）。
    """
    if int(target_user.id) == int(publisher.id):
        raise ApiError(ERR_FORBIDDEN, "不能指派自己")

    if int(target_user.id) in application_service.approved_user_ids(db, task):
        raise ApiError(ERR_CONFLICT, "该用户已通过报名")

    if task.quota is not None and _approved_count(db, task) >= int(task.quota):
        raise ApiError(ERR_CONFLICT, "名额已满")

    now = _now_local()
    row = _find_application(db, int(task.id), int(target_user.id))
    if row is None:
        row = TaskApplication(
            task_id=int(task.id),
            user_id=int(target_user.id),
            status=application_service.APPROVED,
            reason=None,
            created_at=now,
            decided_at=now,
            decided_by=int(publisher.id),
        )
        db.add(row)
    else:
        row.status = application_service.APPROVED
        row.reason = None
        row.decided_at = now
        row.decided_by = int(publisher.id)
        if not row.created_at:
            row.created_at = now

    if task.assignee_id is None:
        task.assignee_id = int(target_user.id)
    if str(task.status) == "published":
        task.status = "claimed"

    # 直接通过同样建立逐人执行行（同一事务，`C-MEMBER@1`）
    member_service.ensure_member(db, task, int(target_user.id))

    notify_service.notify_decided(
        db,
        student_id=int(target_user.id),
        task_id=int(task.id),
        title=str(task.title),
        approved=True,
        commit=False,
    )
    _commit_or_conflict(db, "名额已满，请刷新")


# --------------------------------------------------------------------------- #
# A1 报名
# --------------------------------------------------------------------------- #
@router.post("/tasks/{task_id}/apply")
def apply_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """报名参加任务（多名额模型）：写入 ``pending`` 报名，等待发布者审批。"""
    task = tasks_router._get_task_or_404(db, task_id)
    return ok(create_application(db, task, current_user))


# --------------------------------------------------------------------------- #
# A2 撤回
# --------------------------------------------------------------------------- #
@router.post("/tasks/{task_id}/apply/withdraw")
def withdraw_application(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """撤回报名：仅本人的 ``pending`` 记录可撤回（置 ``cancelled``）。"""
    task = tasks_router._get_task_or_404(db, task_id)
    row = _find_application(db, int(task.id), int(current_user.id))
    if row is None:
        raise ApiError(ERR_NOT_FOUND, "报名记录不存在")

    status = str(row.status)
    if status == application_service.CANCELLED:
        raise ApiError(ERR_CONFLICT, "报名已撤回")
    if status == application_service.REJECTED:
        raise ApiError(ERR_CONFLICT, "报名已被拒绝，可重新报名")
    if status == application_service.APPROVED:
        raise ApiError(ERR_CONFLICT, "发布者已确认，无法撤回")
    if status != application_service.PENDING:
        raise ApiError(ERR_CONFLICT, "任务当前状态不允许该操作")

    row.status = application_service.CANCELLED
    row.reason = None
    row.decided_at = None
    row.decided_by = None

    notify_service.notify_withdrawn(
        db,
        publisher_id=int(task.publisher_id),
        student_name=str(current_user.display_name),
        task_id=int(task.id),
        title=str(task.title),
        commit=False,
    )
    _commit_or_conflict(db, "报名状态已变更，请刷新后重试")
    db.refresh(row)
    return ok(_apply_payload(db, task, row, int(current_user.id)))


# --------------------------------------------------------------------------- #
# A3 发布者查看报名列表
# --------------------------------------------------------------------------- #
@router.get("/tasks/{task_id}/applications")
def list_task_applications(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """查看某任务的全部报名（仅发布者；含 cancelled / rejected，前端自行过滤）。"""
    task = tasks_router._get_task_or_404(db, task_id)
    if int(task.publisher_id) != int(current_user.id):
        raise ApiError(ERR_FORBIDDEN, "只有发布者可以查看报名")

    items = [
        item.model_dump()
        for item in application_service.task_applications(db, int(task.id))
    ]
    return ok({"items": items})


# --------------------------------------------------------------------------- #
# A5 我的报名（先于 A4 声明，避免与 ``{application_id}`` 路径混淆）
# --------------------------------------------------------------------------- #
@router.get("/applications/me")
def my_applications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """当前用户的全部报名（含任务摘要），``created_at DESC, id DESC``。"""
    rows = (
        db.query(TaskApplication)
        .filter(TaskApplication.user_id == int(current_user.id))
        .order_by(TaskApplication.created_at.desc(), TaskApplication.id.desc())
        .all()
    )
    if not rows:
        return ok({"items": []})

    task_ids = {int(row.task_id) for row in rows}
    tasks = db.query(Task).filter(Task.id.in_(task_ids)).all()
    task_map = {int(task.id): task for task in tasks}
    names = _user_names(db, [int(row.user_id) for row in rows])

    items: list[dict[str, Any]] = []
    for row in rows:
        task = task_map.get(int(row.task_id))
        if task is None:
            # 任务已被删除的报名直接丢弃（契约：不返回 task:null）
            continue
        items.append(
            ApplicationItemOut(
                application=_application_out(row, names.get(int(row.user_id), "")),
                task=TaskBrief.model_validate(task),
            ).model_dump()
        )
    return ok({"items": items})


# --------------------------------------------------------------------------- #
# A4 审批
# --------------------------------------------------------------------------- #
@router.post("/applications/{application_id}/decide")
def decide_application(
    application_id: int,
    payload: DecisionIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """审批报名（仅该任务发布者）：通过则置 ``approved`` 并同步任务字段。"""
    row = db.get(TaskApplication, int(application_id))
    if row is None:
        raise ApiError(ERR_NOT_FOUND, "报名记录不存在")

    task = db.get(Task, int(row.task_id))
    if task is None:
        raise ApiError(ERR_NOT_FOUND, "任务不存在")
    if int(task.publisher_id) != int(current_user.id):
        raise ApiError(ERR_FORBIDDEN, "只有发布者可以审批报名")
    if str(row.status) != application_service.PENDING:
        raise ApiError(ERR_CONFLICT, "该报名已处理，请刷新后重试")

    # 拒绝分支：原因必填（4001）
    if not payload.approve:
        reason = (payload.reason or "").strip()
        if not reason:
            raise ApiError(ERR_INVALID_PARAM, "拒绝报名必须填写原因")

        row.status = application_service.REJECTED
        row.reason = reason
        row.decided_at = _now_local()
        row.decided_by = int(current_user.id)

        notify_service.notify_decided(
            db,
            student_id=int(row.user_id),
            task_id=int(task.id),
            title=str(task.title),
            approved=False,
            reason=reason,
            commit=False,
        )
        _commit_or_conflict(db, "该报名已处理，请刷新后重试")
        db.refresh(row)
        return ok(_apply_payload(db, task, row, int(current_user.id)))

    # 通过分支：先完成全部校验（含状态机），再赋值——保证失败时不残留已写数据
    if str(task.status) not in tasks_router.ASSIGN_ALLOWED_STATUSES:
        raise ApiError(ERR_CONFLICT, "任务当前状态不允许审批通过")
    counts = application_service.status_counts_bulk(db, [int(task.id)])
    approved_count = int(
        counts.get(int(task.id), {}).get(application_service.APPROVED, 0)
    )
    if task.quota is not None and approved_count >= int(task.quota):
        raise ApiError(ERR_CONFLICT, "名额已满")
    if str(task.status) == "published":
        tasks_router._ensure_transition(task, "claimed")

    approve_application_row(db, task, row, current_user, commit=False)
    _commit_or_conflict(db, "名额已满，请刷新")
    db.refresh(row)
    return ok(_apply_payload(db, task, row, int(current_user.id)))


__all__ = [
    "router",
    "APPLY_ALLOWED_STATUSES",
    "create_application",
    "approve_application_row",
    "assign_approved",
]