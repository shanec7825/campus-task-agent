"""任务依赖图的唯一读写实现（契约 `C-TASK-GRAPH@1` / `C-ACTIVITY-GRAPH@1`）。

设计口径：

- 依赖边表 ``task_dependencies`` 是新的事实来源；旧列 ``tasks.depends_on`` 保留为
  「首个前置」的兼容索引。读取依赖集合 = 边表 ∪ 旧列（去重保序），写入统一走本模块。
- 校验在写库前完成：存在性、自依赖、重复、同层级、同活动、同组织、无环。
- 图谱只消费调用方已按权限过滤过的任务集合；本模块不新增授权旁路。
- 图规模以活动 / 任务详情为单位，邻接表用一次全表两列查询构建，不做逐节点查询。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Task, TaskDependency

ERR_INVALID_PARAM = 4001


def _normalize_ids(items: Sequence[Any]) -> list[int]:
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


def _adjacency(db: Session) -> dict[int, list[int]]:
    """一次查询构建 ``task_id -> [depends_on_id]`` 邻接表（边表 ∪ 旧列）。"""
    adjacency: dict[int, list[int]] = {}
    for task_id, dep_id in db.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_id).order_by(
            TaskDependency.id.asc()
        )
    ).all():
        adjacency.setdefault(int(task_id), []).append(int(dep_id))
    for task_id, dep_id in db.execute(
        select(Task.id, Task.depends_on).where(Task.depends_on.is_not(None))
    ).all():
        deps = adjacency.setdefault(int(task_id), [])
        if int(dep_id) not in deps:
            deps.insert(0, int(dep_id))
    return adjacency


def dependency_ids_bulk(db: Session, tasks: Sequence[Task] | Sequence[int]) -> dict[int, list[int]]:
    """``task_id -> [前置 id]``，边表 ∪ 旧 ``depends_on``，去重保序。"""
    ordered_ids = _normalize_ids(tasks)
    result: dict[int, list[int]] = {task_id: [] for task_id in ordered_ids}
    if not ordered_ids:
        return result

    for task_id, dep_id in db.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_id)
        .where(TaskDependency.task_id.in_(ordered_ids))
        .order_by(TaskDependency.id.asc())
    ).all():
        result[int(task_id)].append(int(dep_id))

    for task_id, dep_id in db.execute(
        select(Task.id, Task.depends_on).where(
            Task.id.in_(ordered_ids), Task.depends_on.is_not(None)
        )
    ).all():
        deps = result[int(task_id)]
        if int(dep_id) not in deps:
            deps.insert(0, int(dep_id))
    return {task_id: deps for task_id, deps in result.items() if task_id in result}


def _reaches(adjacency: dict[int, list[int]], start_id: int, target_id: int) -> bool:
    """``start_id`` 沿依赖链是否可达 ``target_id``（DFS，防止加入新边后成环）。"""
    stack = [int(start_id)]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if current == int(target_id):
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency.get(current, ()))
    return False


def validate_dependencies(
    db: Session,
    *,
    task_id: int | None,
    parent_id: int | None,
    activity_id: int | None,
    org_id: int | None,
    depends_on_ids: Sequence[int],
) -> list[int]:
    """校验并返回去重后的前置 id 列表；任一规则失败抛 ``4001`` 且不写库。"""
    raw = [int(item) for item in depends_on_ids]
    if len(raw) != len(set(raw)):
        raise ApiError(ERR_INVALID_PARAM, "前置任务不能重复")

    ordered: list[int] = []
    for dep_id in raw:
        if task_id is not None and dep_id == int(task_id):
            raise ApiError(ERR_INVALID_PARAM, "任务不能依赖自己")
        if dep_id not in ordered:
            ordered.append(dep_id)

    if not ordered:
        return []

    rows = db.query(Task).filter(Task.id.in_(ordered)).all()
    tasks = {int(task.id): task for task in rows}
    missing = [dep_id for dep_id in ordered if dep_id not in tasks]
    if missing:
        raise ApiError(ERR_INVALID_PARAM, f"前置任务不存在：#{missing[0]}")

    for dep_id in ordered:
        dependency = tasks[dep_id]
        if dependency.parent_id != parent_id:
            raise ApiError(ERR_INVALID_PARAM, "前置任务必须与当前任务属于同一层级")
        if dependency.activity_id != activity_id:
            raise ApiError(ERR_INVALID_PARAM, "前置任务必须与当前任务属于同一活动")
        if dependency.org_id != org_id:
            raise ApiError(ERR_INVALID_PARAM, "前置任务必须与当前任务属于同一组织")

    if task_id is not None:
        adjacency = _adjacency(db)
        for dep_id in ordered:
            if _reaches(adjacency, dep_id, int(task_id)):
                raise ApiError(ERR_INVALID_PARAM, "前置依赖不能形成环")

    return ordered


def replace_dependencies(db: Session, task: Task, depends_on_ids: Sequence[int]) -> list[int]:
    """用给定集合替换任务的依赖边，并同步旧 ``depends_on`` 为首项。

    调用方负责事务提交；本函数只 flush，不 commit。
    """
    ordered = validate_dependencies(
        db,
        task_id=int(task.id),
        parent_id=task.parent_id,
        activity_id=task.activity_id,
        org_id=task.org_id,
        depends_on_ids=depends_on_ids,
    )
    db.query(TaskDependency).filter(TaskDependency.task_id == int(task.id)).delete(
        synchronize_session=False
    )
    for dep_id in ordered:
        db.add(TaskDependency(task_id=int(task.id), depends_on_id=int(dep_id)))
    task.depends_on = ordered[0] if ordered else None
    db.flush()
    return ordered


def dependency_status_bulk(
    db: Session, tasks: Sequence[Task] | Sequence[int]
) -> dict[int, dict[int, str]]:
    """``task_id -> {depends_on_id: status}``；缺失的前置以 ``missing`` 表达。"""
    ids_map = dependency_ids_bulk(db, tasks)
    all_dep_ids = {dep_id for deps in ids_map.values() for dep_id in deps}
    statuses: dict[int, str] = {}
    if all_dep_ids:
        rows = db.execute(
            select(Task.id, Task.status).where(Task.id.in_(sorted(all_dep_ids)))
        ).all()
        statuses = {int(task_id): str(status) for task_id, status in rows}
    return {
        task_id: {dep_id: statuses.get(dep_id, "missing") for dep_id in deps}
        for task_id, deps in ids_map.items()
    }


def unverified_dependencies(db: Session, task: Task) -> list[dict[str, Any]]:
    """返回未完成（含缺失）前置的 ``{id, title, status}``，供报名错误消息使用。"""
    dep_ids = dependency_ids_bulk(db, [task]).get(int(task.id), [])
    if not dep_ids:
        return []
    rows = db.query(Task).filter(Task.id.in_(dep_ids)).all()
    found = {int(item.id): item for item in rows}
    pending: list[dict[str, Any]] = []
    for dep_id in dep_ids:
        item = found.get(dep_id)
        status = str(item.status) if item is not None else "missing"
        if status != "verified":
            pending.append(
                {
                    "id": dep_id,
                    "title": str(item.title) if item is not None else f"任务 #{dep_id}",
                    "status": status,
                }
            )
    return pending


def neighbor_tasks(db: Session, task: Task) -> tuple[list[Task], list[Task]]:
    """当前任务的直接前置与直接后继（按创建顺序，未做权限过滤）。"""
    task_id = int(task.id)
    dep_ids = dependency_ids_bulk(db, [task]).get(task_id, [])

    dependent_ids: list[int] = []
    for row in db.execute(
        select(TaskDependency.task_id).where(TaskDependency.depends_on_id == task_id)
    ).all():
        if int(row[0]) not in dependent_ids:
            dependent_ids.append(int(row[0]))
    for row in db.execute(select(Task.id).where(Task.depends_on == task_id)).all():
        if int(row[0]) not in dependent_ids:
            dependent_ids.append(int(row[0]))

    all_ids = {dep_id for dep_id in dep_ids} | set(dependent_ids)
    all_ids.discard(task_id)
    found: dict[int, Task] = {}
    if all_ids:
        rows = db.query(Task).filter(Task.id.in_(sorted(all_ids))).all()
        found = {int(item.id): item for item in rows}
    dependencies = [found[dep_id] for dep_id in dep_ids if dep_id in found]
    dependents = [found[item_id] for item_id in dependent_ids if item_id in found]
    return dependencies, dependents


def build_graph_payload(
    db: Session,
    tasks: Sequence[Task],
    visible_ids: Iterable[int],
) -> dict[str, Any]:
    """构造活动 / 任务共用图谱的 ``nodes + edges``。

    节点只含 ``visible_ids``；边两端都可见才保留，避免截断连线造成误解。
    时间字段原样透传，缺失保持 ``None``（不补默认值、不虚构排期）。
    """
    from app.services import application_service

    visible = {int(item) for item in visible_ids}
    nodes_source: list[Task] = []
    seen_nodes: set[int] = set()
    for task in tasks:
        task_id = int(task.id)
        if task_id not in visible or task_id in seen_nodes:
            continue
        seen_nodes.add(task_id)
        nodes_source.append(task)
    names_by_task = application_service.approved_users_bulk(db, nodes_source)
    dep_ids_map = dependency_ids_bulk(db, [task for task in tasks])

    nodes: list[dict[str, Any]] = []
    for task in nodes_source:
        task_id = int(task.id)
        nodes.append(
            {
                "id": task_id,
                "title": str(task.title),
                "status": str(task.status),
                "parent_id": task.parent_id,
                "start_time": task.start_time,
                "deadline": task.deadline,
                "assignee_names": [name for _, name in names_by_task.get(task_id, [])],
            }
        )

    edges: list[dict[str, int]] = []
    seen_edges: set[tuple[int, int]] = set()
    for task in tasks:
        task_id = int(task.id)
        if task_id not in visible:
            continue
        for dep_id in dep_ids_map.get(task_id, []):
            if dep_id not in visible:
                continue
            pair = (dep_id, task_id)
            if pair in seen_edges:
                continue
            seen_edges.add(pair)
            edges.append({"from_id": dep_id, "to_id": task_id})

    return {"nodes": nodes, "edges": edges}


__all__ = [
    "dependency_ids_bulk",
    "validate_dependencies",
    "replace_dependencies",
    "dependency_status_bulk",
    "unverified_dependencies",
    "neighbor_tasks",
    "build_graph_payload",
]