"""活动层级校验与进度聚合的唯一实现（契约 `C-HIERARCHY@1`、`C-ACTIVITY-API@1`）。

除 :func:`publish_batch` 在单事务内写入活动 + 任务 + 依赖外，本模块只读活动与任务数据，提供：

- :func:`resolve_task_placement`：任务创建 / 移动时的三层结构与跨活动校验；
- :func:`publish_batch`：整批发布（`C-BATCH-PUBLISH@1`），先全量校验再写入；
- :func:`build_activity_payload`：``ActivityOut`` 可直读的字典（含 ``owner_name`` 与进度）；
- :func:`build_activity_tree`：``ActivityTaskNode`` 可直读的任务树（一层任务 + 一层子任务）。

口径：子任务全部完成**不**等于任务或活动 ``verified``；``awaiting_owner_confirm`` 只表示
「下层工作已完成，待负责人确认」。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Activity, Organization, Task, User
from app.schemas import ActivityBatchTaskDraft, ActivityPublishBatchIn
from app.services import application_service, authz, task_graph_service

#: 终态：不再参与进度统计（``verified`` 计为完成，``cancelled`` 单独计数）。
TERMINAL_STATUSES: frozenset[str] = frozenset({"verified", "cancelled"})

ERR_ACTIVITY = 4001
ERR_NOT_FOUND = 4040

#: 整批发布未提供 ``reminder_rule``（契约字段集不含该字段），与单任务发布的默认值一致。
DEFAULT_REMINDER_RULE: dict = {"days_before": 1, "day_of": True, "on_overdue": True}


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


def _parent_key(draft: ActivityBatchTaskDraft) -> str | None:
    """草稿的 ``parent_key`` 归一化：去空白，空串视为未声明。"""
    if draft.parent_key is None:
        return None
    normalized = draft.parent_key.strip()
    if not normalized:
        raise ApiError(ERR_ACTIVITY, "父任务 key 不能为空")
    return normalized


def _resolve_batch_keys(drafts: Sequence[ActivityBatchTaskDraft]) -> list[str]:
    """批内 key 列表：缺失按索引生成 ``t0``、``t1``…；重复直接 ``4001``。"""
    keys: list[str] = []
    seen: set[str] = set()
    for index, draft in enumerate(drafts):
        key = (draft.key or "").strip() or f"t{index}"
        if key in seen:
            raise ApiError(ERR_ACTIVITY, f"任务 key 重复：{key}")
        seen.add(key)
        keys.append(key)
    return keys


def _assert_acyclic(adjacency: dict[str, list[str]]) -> None:
    """批内依赖成环检测（迭代 DFS，状态 0/1/2），成环抛 ``4001``。"""
    state: dict[str, int] = {}
    for start in adjacency:
        if state.get(start, 0) == 2:
            continue
        state[start] = 1
        stack: list[tuple[str, Iterator[str]]] = [(start, iter(adjacency.get(start, ())))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                state[node] = 2
                stack.pop()
                continue
            status = state.get(child, 0)
            if status == 1:
                raise ApiError(ERR_ACTIVITY, "前置依赖不能形成环")
            if status == 0:
                state[child] = 1
                stack.append((child, iter(adjacency.get(child, ()))))


def _validate_batch_drafts(drafts: Sequence[ActivityBatchTaskDraft], keys: Sequence[str]) -> None:
    """写入前完成全部任务级校验；任一失败 ``4001`` 且不写库。

    校验项：标题、配额、积分、``parent_id`` 不受支持、父任务存在且为顶层、
    依赖 key 存在、自依赖 / 重复依赖、依赖同层级、成环。
    """
    key_to_index = {key: index for index, key in enumerate(keys)}
    adjacency: dict[str, list[str]] = {}

    for key, draft in zip(keys, drafts):
        if not (draft.title or "").strip():
            raise ApiError(ERR_ACTIVITY, f"任务 {key} 标题不能为空")
        if draft.parent_id is not None:
            raise ApiError(ERR_ACTIVITY, f"任务 {key} 请使用 parent_key 指定父任务")
        if draft.quota is not None and draft.quota < 1:
            raise ApiError(ERR_ACTIVITY, f"任务 {key} 需求人数必须大于 0")
        if draft.credit_reward < 0:
            raise ApiError(ERR_ACTIVITY, f"任务 {key} 完成奖励积分不能为负数")

        parent_key = _parent_key(draft)
        if parent_key is not None:
            if parent_key == key:
                raise ApiError(ERR_ACTIVITY, "任务不能以自己为父任务")
            if parent_key not in key_to_index:
                raise ApiError(ERR_ACTIVITY, f"未知父任务 key：{parent_key}")
            if _parent_key(drafts[key_to_index[parent_key]]) is not None:
                raise ApiError(ERR_ACTIVITY, "子任务不可继续拆分")

        depends_on_keys = list(draft.depends_on_keys)
        if len(depends_on_keys) != len(set(depends_on_keys)):
            raise ApiError(ERR_ACTIVITY, f"任务 {key} 的前置任务不能重复")
        for dep_key in depends_on_keys:
            if dep_key == key:
                raise ApiError(ERR_ACTIVITY, "任务不能依赖自己")
            if dep_key not in key_to_index:
                raise ApiError(ERR_ACTIVITY, f"未知依赖 key：{dep_key}")
            if _parent_key(drafts[key_to_index[dep_key]]) != parent_key:
                raise ApiError(ERR_ACTIVITY, "前置任务必须与当前任务属于同一层级")
        adjacency[key] = depends_on_keys

    _assert_acyclic(adjacency)


def _build_batch_task(
    activity: Activity,
    owner_id: int,
    draft: ActivityBatchTaskDraft,
    *,
    parent_id: int | None,
) -> Task:
    """构造一条待写入的任务行；字段口径与单任务发布保持一致。"""
    return Task(
        parent_id=parent_id,
        activity_id=int(activity.id),
        org_id=activity.org_id,
        title=(draft.title or "").strip(),
        description=draft.description,
        location=draft.location,
        start_time=draft.start_time,
        deadline=draft.deadline,
        quota=draft.quota,
        volunteer_hours=draft.volunteer_hours,
        status="published",
        claim_type=draft.claim_type,
        publisher_id=int(owner_id),
        assignee_id=None,
        depends_on=None,
        sop_guide=draft.sop_guide,
        style_note=draft.style_note,
        extras=draft.extras,
        reminder_rule=dict(DEFAULT_REMINDER_RULE),
        credit_reward=draft.credit_reward,
    )


def publish_batch(
    db: Session, user: User, payload: ActivityPublishBatchIn
) -> tuple[Activity, list[Task]]:
    """整批发布活动与全部任务（`C-BATCH-PUBLISH@1`），失败整体回滚。

    先完成全部校验（活动标题、组织存在与发布权、任务字段、批内 key、依赖、层级、成环），
    再写入活动与任务（先顶层后子任务，逐条 ``flush`` 取 id），依赖经
    ``task_graph_service.replace_dependencies`` 写边表并同步旧 ``depends_on``；
    最后单次 ``commit``。任何异常先 ``rollback`` 再抛出，不留活动 / 任务 / 依赖行。

    Returns:
        ``(activity, tasks)``，``tasks`` 顺序与请求一致。
    """
    activity_in = payload.activity
    title = (activity_in.title or "").strip()
    if not title:
        raise ApiError(ERR_ACTIVITY, "活动标题不能为空")

    if activity_in.org_id is not None and db.get(Organization, int(activity_in.org_id)) is None:
        raise ApiError(ERR_NOT_FOUND, "组织不存在", 404)
    org_id = authz.resolve_task_org(
        db,
        user=user,
        parent=None,
        activity=None,
        org_id=activity_in.org_id,
    )

    drafts = list(payload.tasks)
    keys = _resolve_batch_keys(drafts)
    _validate_batch_drafts(drafts, keys)

    created: dict[str, Task] = {}
    try:
        activity = Activity(
            title=title,
            description=activity_in.description,
            location=activity_in.location,
            start_time=activity_in.start_time,
            deadline=activity_in.deadline,
            owner_id=int(user.id),
            org=activity_in.org,
            org_id=org_id,
            status="published",
        )
        db.add(activity)
        db.flush()

        # 先顶层后子任务：子任务需要父任务的 id，而请求顺序不保证父任务在前。
        for key, draft in zip(keys, drafts):
            if _parent_key(draft) is not None:
                continue
            task = _build_batch_task(activity, int(user.id), draft, parent_id=None)
            db.add(task)
            db.flush()
            created[key] = task
        for key, draft in zip(keys, drafts):
            parent_key = _parent_key(draft)
            if parent_key is None:
                continue
            task = _build_batch_task(
                activity,
                int(user.id),
                draft,
                parent_id=int(created[parent_key].id),
            )
            db.add(task)
            db.flush()
            created[key] = task

        for key, draft in zip(keys, drafts):
            dependency_ids = [int(created[dep_key].id) for dep_key in draft.depends_on_keys]
            if dependency_ids:
                task_graph_service.replace_dependencies(db, created[key], dependency_ids)

        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(activity)
    ordered = [created[key] for key in keys]
    for task in ordered:
        db.refresh(task)
    return activity, ordered


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
    "DEFAULT_REMINDER_RULE",
    "resolve_task_placement",
    "publish_batch",
    "build_activity_payload",
    "build_activity_tree",
]