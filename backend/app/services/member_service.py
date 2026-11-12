"""逐人成员执行服务与任务聚合状态（契约 `C-MEMBER@1`，owner = T2）。

职责边界：

- ``task_applications`` 是报名/审批身份记录（唯一写入位置是 ``routers/applications.py``），
  本模块只**只读**聚合 approved 成员；
- ``task_members`` 是逐人执行记录，本模块是唯一读写入口；
- 任务聚合状态由 :func:`sync_task_status` 按成员状态派生，永不把成员状态改写成
  ``overdue``（``overdue`` 只是截止时间标记）。

事务边界：本模块所有写函数只 ``flush``，**不 commit**；调用方（路由 / 调度器）
持有事务并统一提交。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Task, TaskMember
from app.services import application_service
from app.services.task_state import ALLOWED_TRANSITIONS

logger = logging.getLogger(__name__)

ERR_CONFLICT = 4090
_CONFLICT_MESSAGE = "任务当前状态不允许该操作"

MEMBER_NOT_STARTED = "not_started"
MEMBER_IN_PROGRESS = "in_progress"
MEMBER_SUBMITTED = "submitted"
MEMBER_REJECTED = "rejected"
MEMBER_VERIFIED = "verified"

#: 已进入「等验收 / 已通过」的成员状态（提醒与逾期扣分跳过）
FINISHED_STATUSES = frozenset({MEMBER_SUBMITTED, MEMBER_VERIFIED})


@dataclass
class MemberView:
    """单名 approved 成员的读视图（无 ``task_members`` 行时为 ``not_started``）。"""

    user_id: int
    user_name: str
    status: str
    rejection_reason: str | None = None
    submitted_at: str | None = None
    verified_at: str | None = None


def _now_local() -> str:
    """服务器本地时间，格式与全库口径一致：``YYYY-MM-DD HH:MM:SS``。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_DEADLINE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def _deadline_is_future(deadline: str | None) -> bool:
    """``deadline`` 是否可解析且严格晚于当前本地时间。

    ``overdue`` 只能由「仍合格的新截止时间」拉回进行中状态；自然语言或非法值
    一律视为不可用（保持 overdue），避免出现「调度器置逾期 → 聚合状态拉回 → 调度器
    再置逾期」的状态抖动，也避免丢失逾期标记。
    """
    if not deadline:
        return False
    raw = str(deadline).strip()
    if not raw:
        return False

    now = datetime.now()
    for fmt in _DEADLINE_FORMATS:
        try:
            return datetime.strptime(raw, fmt) > now
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed > now


def _member_rows(db: Session, task_ids: Sequence[int]) -> dict[tuple[int, int], TaskMember]:
    """一次 IN 查询取成员行，键为 ``(task_id, user_id)``。"""
    ids = sorted({int(task_id) for task_id in task_ids})
    if not ids:
        return {}
    rows = db.scalars(select(TaskMember).where(TaskMember.task_id.in_(ids))).all()
    return {(int(row.task_id), int(row.user_id)): row for row in rows}


def _member_payload(row: TaskMember | None, user_id: int, user_name: str) -> dict:
    """成员行（可缺省）→ ``MemberOut`` 对齐字典；缺失行报告为 ``not_started``。"""
    return {
        "user_id": int(user_id),
        "user_name": str(user_name),
        "status": str(row.status) if row is not None else MEMBER_NOT_STARTED,
        "rejection_reason": row.rejection_reason if row is not None else None,
        "submitted_at": row.submitted_at if row is not None else None,
        "verified_at": row.verified_at if row is not None else None,
        "updated_at": row.updated_at if row is not None else None,
    }


# --------------------------------------------------------------------------- #
# 只读聚合
# --------------------------------------------------------------------------- #
def effective_members(db: Session, task: Task) -> list[MemberView]:
    """该任务的 approved 成员（含 legacy 回退），按报名先后排序。

    缺少 ``task_members`` 行的成员报告为 ``not_started``，**不写库**。
    """
    task_id = int(task.id)
    approved = application_service.approved_users_bulk(db, [task]).get(task_id, [])
    rows = _member_rows(db, [task_id])
    views: list[MemberView] = []
    for user_id, name in approved:
        row = rows.get((task_id, int(user_id)))
        views.append(
            MemberView(
                user_id=int(user_id),
                user_name=str(name),
                status=str(row.status) if row is not None else MEMBER_NOT_STARTED,
                rejection_reason=row.rejection_reason if row is not None else None,
                submitted_at=row.submitted_at if row is not None else None,
                verified_at=row.verified_at if row is not None else None,
            )
        )
    return views


def members_payload_bulk(db: Session, tasks: Sequence[Task]) -> dict[int, list[dict]]:
    """批量成员序列化载荷：``task_id -> [MemberOut 字段字典]``。

    一次 approved 批量查询 + 一次 members 批量查询；入参中每个任务 id
    都必须出现在返回值里（缺成员时为空列表），供 ``TaskOut.members`` 直接取值。
    """
    task_ids = [int(task.id) for task in tasks if getattr(task, "id", None) is not None]
    if not task_ids:
        return {}
    approved = application_service.approved_users_bulk(db, task_ids)
    rows = _member_rows(db, task_ids)
    return {
        task_id: [
            _member_payload(rows.get((task_id, int(user_id))), int(user_id), name)
            for user_id, name in approved.get(task_id, [])
        ]
        for task_id in task_ids
    }


# --------------------------------------------------------------------------- #
# 写操作（只 flush，不 commit）
# --------------------------------------------------------------------------- #
def ensure_member(db: Session, task: Task, user_id: int) -> TaskMember:
    """取成员行，不存在则创建 ``not_started`` 行（不 commit）。"""
    task_id = int(task.id)
    uid = int(user_id)
    row = db.scalars(
        select(TaskMember)
        .where(TaskMember.task_id == task_id, TaskMember.user_id == uid)
        .limit(1)
    ).first()
    if row is not None:
        return row

    row = TaskMember(
        task_id=task_id,
        user_id=uid,
        status=MEMBER_NOT_STARTED,
        rejection_reason=None,
        submitted_at=None,
        verified_at=None,
        updated_at=_now_local(),
    )
    db.add(row)
    db.flush()
    return row


def _aggregate_status(members: Sequence[MemberView]) -> str | None:
    """按 §2.1 规则由成员状态派生任务聚合状态；无成员时返回 ``None``。"""
    if not members:
        return None
    statuses = [member.status for member in members]
    if all(status == MEMBER_VERIFIED for status in statuses):
        return MEMBER_VERIFIED
    if MEMBER_REJECTED in statuses:
        return MEMBER_IN_PROGRESS
    if MEMBER_SUBMITTED in statuses:
        return MEMBER_SUBMITTED
    if MEMBER_IN_PROGRESS in statuses:
        return MEMBER_IN_PROGRESS
    return "claimed"


def sync_task_status(db: Session, task: Task) -> str:
    """按成员状态重算并（在合法流转内）写入 ``task.status``，返回结果状态。

    - 只应用 :data:`task_state.ALLOWED_TRANSITIONS` 中存在的流转；
    - ``cancelled`` / ``verified`` 为终态，天然不会被改写；
    - 无有效成员时保持当前状态不变；
    - ``overdue → claimed|in_progress`` 仅在 deadline 可解析且晚于当前时间时成立
      （发布者改期恢复），否则保持 ``overdue``；成员已提交/已验收时仍可迁出。
    """
    target = _aggregate_status(effective_members(db, task))
    current = str(task.status)
    if target is None or target == current:
        return current
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        return current
    if (
        current == "overdue"
        and target in ("claimed", MEMBER_IN_PROGRESS)
        and not _deadline_is_future(task.deadline)
    ):
        logger.info(
            "逾期任务保持 overdue task_id=%s target=%s deadline=%s",
            task.id,
            target,
            task.deadline,
        )
        return current

    task.status = target
    db.flush()
    logger.info("任务聚合状态重算 task_id=%s %s -> %s", task.id, current, target)
    return target


def record_progress(db: Session, task: Task, user_id: int) -> TaskMember:
    """记录成员开始/推进进度：``not_started|rejected|in_progress → in_progress``。"""
    member = ensure_member(db, task, user_id)
    status = str(member.status)
    if status in FINISHED_STATUSES:
        raise ApiError(ERR_CONFLICT, _CONFLICT_MESSAGE)

    member.status = MEMBER_IN_PROGRESS
    member.updated_at = _now_local()
    db.flush()
    sync_task_status(db, task)
    return member


def record_submit(db: Session, task: Task, user_id: int) -> tuple[TaskMember, bool]:
    """成员提交：``in_progress|rejected → submitted``；已提交幂等返回 ``False``。"""
    member = ensure_member(db, task, user_id)
    status = str(member.status)
    if status == MEMBER_SUBMITTED:
        return member, False
    if status not in (MEMBER_IN_PROGRESS, MEMBER_REJECTED):
        raise ApiError(ERR_CONFLICT, _CONFLICT_MESSAGE)

    now = _now_local()
    member.status = MEMBER_SUBMITTED
    member.submitted_at = now
    member.rejection_reason = None
    member.updated_at = now
    db.flush()
    sync_task_status(db, task)
    return member, True


def record_verification(
    db: Session,
    task: Task,
    user_id: int,
    *,
    passed: bool,
    reason: str | None,
) -> TaskMember:
    """发布者验收单名成员：仅 ``submitted`` 可被通过或退回。"""
    member = ensure_member(db, task, user_id)
    if str(member.status) != MEMBER_SUBMITTED:
        raise ApiError(ERR_CONFLICT, _CONFLICT_MESSAGE)

    now = _now_local()
    if passed:
        member.status = MEMBER_VERIFIED
        member.verified_at = now
        member.rejection_reason = None
    else:
        member.status = MEMBER_REJECTED
        member.rejection_reason = reason
    member.updated_at = now
    db.flush()
    sync_task_status(db, task)
    return member


__all__ = [
    "MEMBER_NOT_STARTED",
    "MEMBER_IN_PROGRESS",
    "MEMBER_SUBMITTED",
    "MEMBER_REJECTED",
    "MEMBER_VERIFIED",
    "FINISHED_STATUSES",
    "MemberView",
    "effective_members",
    "members_payload_bulk",
    "ensure_member",
    "sync_task_status",
    "record_progress",
    "record_submit",
    "record_verification",
]