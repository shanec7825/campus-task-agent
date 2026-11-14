"""活动层级校验与进度聚合的唯一实现（契约 `C-HIERARCHY@1`、`C-ACTIVITY-API@1`）。

本模块只读活动与任务数据（除调用方自行插入活动行外不写库），提供：

- :func:`resolve_task_placement`：任务创建 / 移动时的三层结构与跨活动校验；
- :func:`build_activity_payload`：``ActivityOut`` 可直读的字典（含 ``owner_name`` 与进度）；
- :func:`build_activity_tree`：``ActivityTaskNode`` 可直读的任务树（一层任务 + 一层子任务）。

口径：子任务全部完成**不**等于任务或活动 ``verified``；``awaiting_owner_confirm`` 只表示
「下层工作已完成，待负责人确认」。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Activity, Task, User
from app.services import application_service

#: 终态：不再参与进度统计（``verified`` 计为完成，``cancelled`` 单独计数）。
TERMINAL_STATUSES: frozenset[str] = frozenset({"verified", "cancelled"})

ERR_ACTIVITY = 4001


def resolve_task_placement(
    db: Session,
    *,
    parent: Task | None,
    activity_id: int | None,
    task_id: int | None = None,
    task: Task | None = None,
) -> int | None:
    """返回任务最终落库的 ``activity_id``；非法层级一律 ``4001`` 且不写库。

    ``task`` 为被移动的任务本身：移动时若未显式给出 ``parent``，则以 ``task.parent_id``
    指向的任务作为有效父任务，保证不因绕过请求参数而破坏「子任务与父任务同活动」的口径。
    """
    effective_parent = parent
    if task is not None and parent is None and task.parent_id is not None:
        effective_parent = db.get(Task, int(task.parent_id))

    if task_id is not None and parent is not None and int(parent.id) == int(task_id):
        raise ApiError(ERR_ACTIVITY, "任务不能以自己为父任务")
    if parent is not None and parent.parent_id is not None:
        raise ApiError(ERR_ACTIVITY, "子任务不可继续拆分")
    has_children = (
        task is not None
        and db.query(Task).filter(Task.parent_id == int(task.id)).first() is not None
    )
    if task is not None and parent is not None and has_children:
        raise ApiError(ERR_ACTIVITY, "已有子任务的任务不可成为子任务")
    # 有子任务的任务直接换活动会把子任务留在旧活动：只能先移动 / 清空子任务。
    if (
        has_children
        and parent is None
        and int(activity_id or 0) != int(task.activity_id or 0)
    ):
        raise ApiError(ERR_ACTIVITY, "存在子任务的任务不可直接变更所属活动")
    if (
        effective_parent is not None
        and activity_id is not None
        and effective_parent.activity_id is not None
        and int(activity_id) != int(effective_parent.activity_id)
    ):
        raise ApiError(ERR_ACTIVITY, "子任务必须与父任务属于同一活动")
    if activity_id is not None and db.get(Activity, int(activity_id)) is None:
        raise ApiError(ERR_ACTIVITY, "活动不存在")

    return effective_parent.activity_id if effective_parent is not None else activity_id


def _activity_tasks(db: Session, activity_id: int) -> list[Task]:
    """该活动下全部任务（一层与子任务），按 ``created_at ASC, id ASC``。"""
    return list(
        db.scalars(
            select(Task)
            .where(Task.activity_id == int(activity_id))
            .order_by(Task.created_at.asc(), Task.id.asc())
        ).all()
    )


def _progress_payload(tasks: list[Task]) -> dict:
    """按契约口径聚合进度；子任务完成不改写任何任务 / 活动状态。"""
    top_tasks = [task for task in tasks if task.parent_id is None]
    subtasks = [task for task in tasks if task.parent_id is not None]

    active_top = [task for task in top_tasks if str(task.status) != "cancelled"]
    total_tasks = len(active_top)
    completed_tasks = sum(1 for task in active_top if str(task.status) == "verified")
    cancelled_tasks = len(top_tasks) - len(active_top)

    children_by_parent: dict[int, list[Task]] = {}
    for subtask in subtasks:
        children_by_parent.setdefault(int(subtask.parent_id), []).append(subtask)

    pending_top = [task for task in active_top if str(task.status) != "verified"]
    # 只有「有子任务且子任务全部完成」的未验收任务才提示待确认；
    # 任一未验收任务仍存在未验收子任务时，下层工作尚未完成，不提示。
    has_completed_children = any(
        children and all(str(child.status) == "verified" for child in children)
        for children in (children_by_parent.get(int(task.id), []) for task in pending_top)
    )
    has_unfinished_children = any(
        any(str(child.status) != "verified" for child in children)
        for children in (children_by_parent.get(int(task.id), []) for task in pending_top)
    )
    awaiting_owner_confirm = has_completed_children and not has_unfinished_children

    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "cancelled_tasks": cancelled_tasks,
        "subtask_total": len(subtasks),
        "subtask_completed": sum(1 for subtask in subtasks if str(subtask.status) == "verified"),
        "percent": 0 if total_tasks == 0 else round(completed_tasks * 100 / total_tasks),
        "awaiting_owner_confirm": awaiting_owner_confirm,
    }


def _owner_name(db: Session, owner_id: int) -> str:
    owner = db.get(User, int(owner_id))
    return str(owner.display_name) if owner is not None else ""


def build_activity_payload(db: Session, activity: Activity) -> dict:
    """``ActivityOut`` 可直读的字典（含 ``owner_name`` 与 ``progress``）。"""
    tasks = _activity_tasks(db, int(activity.id))
    return {
        "id": int(activity.id),
        "title": str(activity.title),
        "description": activity.description,
        "location": activity.location,
        "start_time": activity.start_time,
        "deadline": activity.deadline,
        "owner_id": int(activity.owner_id),
        "owner_name": _owner_name(db, int(activity.owner_id)),
        "org": activity.org,
        "status": str(activity.status),
        "created_at": str(activity.created_at),
        "progress": _progress_payload(tasks),
    }


def build_activity_tree(db: Session, activity: Activity) -> list[dict]:
    """``ActivityTaskNode`` 可直读的任务树：一层任务按创建顺序，子任务同序挂载。"""
    tasks = _activity_tasks(db, int(activity.id))
    names_by_task = application_service.approved_users_bulk(db, tasks)
    activity_id = int(activity.id)

    top_tasks = [task for task in tasks if task.parent_id is None]
    nodes: dict[int, dict] = {}
    for task in top_tasks:
        task_id = int(task.id)
        rows = names_by_task.get(task_id, [])
        nodes[task_id] = {
            "id": task_id,
            "activity_id": activity_id,
            "title": str(task.title),
            "status": str(task.status),
            "start_time": task.start_time,
            "deadline": task.deadline,
            "assignees": _assignees_payload(rows),
            "assignee_names": [name for _, name in rows],
            "completed_children": 0,
            "total_children": 0,
            "children": [],
        }

    for subtask in tasks:
        if subtask.parent_id is None:
            continue
        parent_node = nodes.get(int(subtask.parent_id))
        if parent_node is None:
            continue
        subtask_id = int(subtask.id)
        rows = names_by_task.get(subtask_id, [])
        parent_node["children"].append(
            {
                "id": subtask_id,
                "activity_id": activity_id,
                "title": str(subtask.title),
                "status": str(subtask.status),
                "start_time": subtask.start_time,
                "deadline": subtask.deadline,
                "assignees": _assignees_payload(rows),
                "assignee_names": [name for _, name in rows],
            }
        )

    for node in nodes.values():
        children = node["children"]
        node["total_children"] = len(children)
        node["completed_children"] = sum(1 for child in children if child["status"] == "verified")

    return [nodes[int(task.id)] for task in top_tasks]


def _assignees_payload(rows: list[tuple[int, str]]) -> list[dict]:
    """``(user_id, name)`` → ``ActivityAssigneeOut`` 字典，顺序与 ``assignee_names`` 一致。"""
    return [{"user_id": int(user_id), "name": name} for user_id, name in rows]


__all__ = [
    "TERMINAL_STATUSES",
    "resolve_task_placement",
    "build_activity_payload",
    "build_activity_tree",
]