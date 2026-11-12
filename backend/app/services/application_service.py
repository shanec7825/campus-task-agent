"""报名数据只读聚合服务（契约 `C-DATA@2` 第 D 节，owner = T1）。

本模块**只读**：绝不写 ``task_applications``（写入统一由 T2 的
``routers/applications.py`` / ``routers/tasks.py`` 完成，避免两处写同一张表）。

legacy 回退：任务无任何 ``approved`` 行且 ``tasks.assignee_id`` 非空时，读取视角视为该
用户已 ``approved``（P1 单负责人数据不做迁移）。

实现约束：
1. 批量函数一律「一次 IN 查询」完成聚合，禁止循环单查（禁止 N+1）；
2. 只允许导入 ``app.models`` / ``app.schemas`` / ``sqlalchemy``，禁止导入 ``app.routers``
   （避免循环导入）。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Task, TaskApplication, User
from app.schemas import ApplicationOut

# --------------------------------------------------------------------------- #
# 状态常量（T2 复用，禁止在别处另写状态字面量）
# --------------------------------------------------------------------------- #

PENDING: str = "pending"
APPROVED: str = "approved"
REJECTED: str = "rejected"
CANCELLED: str = "cancelled"

#: 全部合法状态（应用层校验 ``status`` 取值）
APPLICATION_STATUSES: frozenset[str] = frozenset({PENDING, APPROVED, REJECTED, CANCELLED})

#: 阻止重复报名的状态（同人同任务已有其一即视为「已报名」）
BLOCKING_STATUSES: tuple[str, str] = (PENDING, APPROVED)


# --------------------------------------------------------------------------- #
# 内部工具（纯查询辅助，均以 IN 条件一次性取数）
# --------------------------------------------------------------------------- #


def _normalize_task_ids(items: Sequence[Any]) -> list[int]:
    """把 ``Sequence[Task]`` 或 ``Sequence[int]`` 统一成去重保序的 int 列表。"""
    ordered: list[int] = []
    seen: set[int] = set()
    for item in items:
        raw_id = getattr(item, "id", item)
        if raw_id is None:
            continue
        task_id = int(raw_id)
        if task_id in seen:
            continue
        seen.add(task_id)
        ordered.append(task_id)
    return ordered


def _fetch_rows(db: Session, task_ids: Sequence[int]) -> list[TaskApplication]:
    """一次 IN 查询取出若干任务的全部报名行（不做状态过滤）。"""
    if not task_ids:
        return []
    stmt = select(TaskApplication).where(TaskApplication.task_id.in_(list(task_ids)))
    return list(db.scalars(stmt).all())


def _group_by_task(rows: Iterable[TaskApplication]) -> dict[int, list[TaskApplication]]:
    """把报名行按 ``task_id`` 分组（组内保持稳定顺序，不依赖数据库返回顺序）。"""
    grouped: dict[int, list[TaskApplication]] = {}
    for row in rows:
        grouped.setdefault(int(row.task_id), []).append(row)
    for task_rows in grouped.values():
        task_rows.sort(key=lambda row: (str(row.created_at or ""), int(row.id or 0)))
    return grouped


def _assignee_map(db: Session, task_ids: Sequence[int]) -> dict[int, int | None]:
    """一次 IN 查询取 ``tasks.assignee_id``（legacy 回退的唯一依据）。"""
    if not task_ids:
        return {}
    stmt = select(Task.id, Task.assignee_id).where(Task.id.in_(list(task_ids)))
    return {
        int(task_id): (int(assignee_id) if assignee_id is not None else None)
        for task_id, assignee_id in db.execute(stmt).all()
    }


def _display_names(db: Session, user_ids: Iterable[int]) -> dict[int, str]:
    """一次 IN 查询取 ``users.display_name``；缺失用户以空串兜底（与 P1 口径一致）。"""
    ids = sorted({int(user_id) for user_id in user_ids})
    if not ids:
        return {}
    stmt = select(User.id, User.display_name).where(User.id.in_(ids))
    return {int(user_id): str(display_name) for user_id, display_name in db.execute(stmt).all()}


def _approved_ids_by_task(db: Session, task_ids: Sequence[int]) -> dict[int, list[int]]:
    """``task_id -> [approved user_id]``（按报名先后），含 legacy 回退。

    一次应用行查询 + 一次 tasks 查询；入参中不存在的任务同样返回键（空列表或回退值）。
    """
    ordered_ids = _normalize_task_ids(task_ids)
    if not ordered_ids:
        return {}
    grouped = _group_by_task(_fetch_rows(db, ordered_ids))
    assignees = _assignee_map(db, ordered_ids)

    result: dict[int, list[int]] = {}
    for task_id in ordered_ids:
        approved_ids = [
            int(row.user_id) for row in grouped.get(task_id, ()) if str(row.status) == APPROVED
        ]
        if not approved_ids:
            legacy_id = assignees.get(task_id)
            # legacy 回退只用于“该负责人没有任何报名行”的旧数据；
            # 若其报名行已明确 rejected/cancelled，不得再凭空视为 approved（避免读路径自相矛盾）。
            has_own_row = legacy_id is not None and any(
                int(row.user_id) == int(legacy_id) for row in grouped.get(task_id, ())
            )
            if legacy_id is not None and not has_own_row:
                approved_ids = [legacy_id]
        result[task_id] = approved_ids
    return result


# --------------------------------------------------------------------------- #
# 对外只读接口
# --------------------------------------------------------------------------- #


def approved_user_ids(db: Session, task: Task) -> list[int]:
    """该任务 approved 用户 id 列表，按 ``created_at ASC, id ASC``。

    无 approved 行且 ``task.assignee_id`` 非空时返回 ``[int(task.assignee_id)]``（legacy），
    否则返回 ``[]``。
    """
    task_id = int(task.id)
    return _approved_ids_by_task(db, [task_id]).get(task_id, [])


def status_counts(db: Session, task: Task) -> dict[str, int]:
    """单个任务的状态计数：``{"pending": n, "approved": m}``（含 legacy 回退）。"""
    task_id = int(task.id)
    return status_counts_bulk(db, [task_id])[task_id]


def status_counts_bulk(db: Session, task_ids: Sequence[int]) -> dict[int, dict[str, int]]:
    """批量状态计数：``task_id -> {"pending": n, "approved": m}``。

    实现要点：
    - 一次 IN 查询 applications + 一次 IN 查询 tasks（取 ``assignee_id`` 做 legacy 回退）；
    - **每个入参 task_id 都必须出现在返回值里**（默认 0 值），供 ``TaskOut`` 直接取值，
      否则消费方会 ``KeyError``。
    """
    ordered_ids = _normalize_task_ids(task_ids)
    if not ordered_ids:
        return {}

    counts: dict[int, dict[str, int]] = {
        task_id: {PENDING: 0, APPROVED: 0} for task_id in ordered_ids
    }
    approved_seen: set[int] = set()
    own_rows: set[tuple[int, int]] = set()

    for row in _fetch_rows(db, ordered_ids):
        task_id = int(row.task_id)
        if task_id not in counts:
            continue
        own_rows.add((task_id, int(row.user_id)))
        status = str(row.status)
        if status == PENDING:
            counts[task_id][PENDING] += 1
        elif status == APPROVED:
            counts[task_id][APPROVED] += 1
            approved_seen.add(task_id)

    for task_id, assignee_id in _assignee_map(db, ordered_ids).items():
        if assignee_id is None or task_id in approved_seen:
            continue
        # 与 _approved_ids_by_task 的 legacy 回退口径一致：负责人已有报名行时
        # （例如 rejected/cancelled）不再凭空计为 approved。
        if (task_id, int(assignee_id)) in own_rows:
            continue
        counts[task_id][APPROVED] += 1

    return counts


def approved_users_bulk(
    db: Session, tasks: Sequence[Task] | Sequence[int]
) -> dict[int, list[tuple[int, str]]]:
    """批量版本：``task_id -> [(user_id, display_name)]``，同样的 legacy 回退与排序。

    入参兼容 ``Sequence[Task]``（``TaskOut`` 序列化入口）与 ``Sequence[int]``（只拿到 id 时）。
    实现约束：对入参一次 IN 查询 applications、一次 IN 查询 users、一次 IN 查询 tasks，
    禁止 N+1。
    """
    approved_by_task = _approved_ids_by_task(db, _normalize_task_ids(tasks))
    all_ids = [user_id for ids in approved_by_task.values() for user_id in ids]
    names = _display_names(db, all_ids)
    return {
        task_id: [(user_id, names.get(user_id, "")) for user_id in user_ids]
        for task_id, user_ids in approved_by_task.items()
    }


def approved_user_rows_bulk(
    db: Session, tasks: Sequence[Task] | Sequence[int]
) -> dict[int, list[User]]:
    """``task_id -> [User]`` 形态（需要 ``role`` / ``org`` 等完整字段时使用）。

    与 :func:`approved_users_bulk` 共享同一套 approved 计算与 legacy 回退；
    用户已被删除时跳过该元素（不回填占位对象）。
    """
    approved_by_task = _approved_ids_by_task(db, _normalize_task_ids(tasks))
    all_ids = sorted({user_id for ids in approved_by_task.values() for user_id in ids})
    users: dict[int, User] = {}
    if all_ids:
        stmt = select(User).where(User.id.in_(all_ids))
        users = {int(user.id): user for user in db.scalars(stmt).all()}
    return {
        task_id: [users[user_id] for user_id in user_ids if user_id in users]
        for task_id, user_ids in approved_by_task.items()
    }


def user_application_status(db: Session, task_id: int, user_id: int | None) -> str | None:
    """当前用户对该任务的状态（``UNIQUE(task_id, user_id)`` 单行）。

    - ``user_id`` 为 ``None`` 或无报名记录且不构成 legacy 回退时返回 ``None``；
    - legacy 回退：本人是 ``tasks.assignee_id`` 且该任务尚无任何 approved 行 → ``"approved"``。
      与 :func:`approved_user_ids` 的回退口径严格一致（避免两处结论互相矛盾）。
    """
    if user_id is None:
        return None

    tid = int(task_id)
    uid = int(user_id)
    stmt = (
        select(TaskApplication)
        .where(TaskApplication.task_id == tid, TaskApplication.user_id == uid)
        .limit(1)
    )
    row = db.scalars(stmt).first()
    if row is not None:
        return str(row.status)

    task = db.get(Task, tid)
    if task is None or task.assignee_id is None or int(task.assignee_id) != uid:
        return None

    approved_total = db.scalar(
        select(func.count())
        .select_from(TaskApplication)
        .where(TaskApplication.task_id == tid, TaskApplication.status == APPROVED)
    )
    return APPROVED if not approved_total else None


def my_application_status(db: Session, task_id: int, user_id: int | None) -> str | None:
    """:func:`user_application_status` 的语义别名（``my_*`` 命名，供路由层直接调用）。"""
    return user_application_status(db, task_id, user_id)


def is_approved_participant(db: Session, task: Task, user_id: int) -> bool:
    """是否 approved 成员（含 legacy 回退）。用于进度 / 提交 / 签到的权限判断。"""
    if user_id is None:
        return False
    return int(user_id) in approved_user_ids(db, task)


def is_active_participant(db: Session, task: Task, user_id: int) -> bool:
    """是否在建成员：approved（含回退）或 pending。用于展示型权限判断。"""
    status = user_application_status(db, task.id, user_id)
    return status in BLOCKING_STATUSES


def task_applications(db: Session, task_id: int) -> list[ApplicationOut]:
    """某任务的全部报名记录（含 ``user_name``），按 ``created_at ASC, id ASC``。

    发布者查看报名列表（A3）直接使用；名称通过一次 IN 查询 ``users`` 批量填充。
    """
    ordered = sorted(
        _fetch_rows(db, [int(task_id)]),
        key=lambda row: (str(row.created_at or ""), int(row.id or 0)),
    )
    names = _display_names(db, [int(row.user_id) for row in ordered])
    return [
        ApplicationOut(
            id=int(row.id),
            task_id=int(row.task_id),
            user_id=int(row.user_id),
            user_name=names.get(int(row.user_id), ""),
            status=str(row.status),
            reason=row.reason,
            created_at=str(row.created_at or ""),
            decided_at=row.decided_at,
        )
        for row in ordered
    ]


__all__ = [
    # 状态常量
    "PENDING",
    "APPROVED",
    "REJECTED",
    "CANCELLED",
    "APPLICATION_STATUSES",
    "BLOCKING_STATUSES",
    # 只读聚合
    "approved_user_ids",
    "status_counts",
    "status_counts_bulk",
    "approved_users_bulk",
    "approved_user_rows_bulk",
    "user_application_status",
    "my_application_status",
    "is_approved_participant",
    "is_active_participant",
    "task_applications",
]