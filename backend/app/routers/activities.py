"""活动路由（契约 `C-ACTIVITY-API@1`，owner = T2）。

三个端点，全部要求登录：
1. ``GET /api/activities``：活动列表（``created_at DESC, id DESC``），带 ``owner_name`` 与 ``progress``；
2. ``GET /api/activities/{activity_id}``：活动详情，附第一层任务与子任务树；
3. ``POST /api/activities``：创建活动，``owner_id`` 取当前用户、``status`` 固定 ``published``。

进度与树结构**只**由 ``activity_service`` 生成，本模块不重复实现聚合逻辑；读取接口不写库。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf
from app.errors import ApiError, ok
from app.models import Activity, Task, User
from app.schemas import ActivityCreate, ActivityDetailOut, ActivityListOut, ActivityOut
from app.services import activity_service, authz

router = APIRouter(
    prefix="/api/activities", tags=["activities"], dependencies=[Depends(require_csrf)]
)


def _visible_activity_condition(db: Session, user: User) -> ColumnElement[bool]:
    """活动可见性的 SQL 条件（`C-AUTHZ@1` 规则，禁止取全表后在 Python 过滤）。

    可见 = 我是负责人 | 我是所属组织 ``admin`` | 该活动下存在我可见的任务。
    """
    conditions = [Activity.owner_id == int(user.id)]
    admin_org_ids = authz.org_ids_for(db, user, ("admin",))
    if admin_org_ids:
        conditions.append(Activity.org_id.in_(admin_org_ids))
    conditions.append(
        exists(
            select(Task.id).where(
                Task.activity_id == Activity.id,
                authz.visible_task_filter(db, user),
            )
        )
    )
    return or_(*conditions)


def _owner_names(db: Session, owner_ids: set[int]) -> dict[int, str]:
    """批量解析负责人昵称，避免逐行查库。"""
    if not owner_ids:
        return {}
    rows = db.query(User.id, User.display_name).filter(User.id.in_(owner_ids)).all()
    return {int(row[0]): str(row[1]) for row in rows}


def _activity_payload(
    db: Session,
    activity: Activity,
    owner_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    """取服务层 payload，并保证 ``owner_name`` 与 ``org_id`` 已填充。"""
    payload = activity_service.build_activity_payload(db, activity)
    if not payload.get("owner_name"):
        names = owner_names if owner_names is not None else _owner_names(db, {int(activity.owner_id)})
        payload["owner_name"] = names.get(int(activity.owner_id), "")
    payload["org_id"] = activity.org_id
    return payload


def _visible_activity_tasks(
    db: Session, activity: Activity, user: User
) -> list[dict[str, Any]]:
    """活动任务树剔除不可见任务（父任务不可见时整棵子树不出现）。"""
    tree = activity_service.build_activity_tree(db, activity)
    node_ids: set[int] = set()
    for node in tree:
        node_ids.add(int(node["id"]))
        node_ids.update(int(child["id"]) for child in (node.get("children") or []))

    tasks: dict[int, Task] = {}
    if node_ids:
        rows = db.query(Task).filter(Task.id.in_(node_ids)).all()
        tasks = {int(task.id): task for task in rows}

    visible_tree: list[dict[str, Any]] = []
    for node in tree:
        task = tasks.get(int(node["id"]))
        if task is None or not authz.can_view_task(db, user, task):
            continue
        node["children"] = [
            child
            for child in (node.get("children") or [])
            if int(child["id"]) in tasks and authz.can_view_task(db, user, tasks[int(child["id"])])
        ]
        visible_tree.append(node)
    return visible_tree


@router.get("")
def list_activities(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """活动列表：新的在前，每项带负责人昵称与整体进度。"""
    activities = (
        db.query(Activity)
        .filter(_visible_activity_condition(db, current_user))
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .all()
    )
    names = _owner_names(db, {int(item.owner_id) for item in activities})
    items = [
        ActivityOut.model_validate(_activity_payload(db, item, names)) for item in activities
    ]
    return ok(ActivityListOut(items=items).model_dump())


@router.get("/{activity_id}")
def get_activity(
    activity_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """活动详情：``tasks`` 为该活动的第一层任务（含子任务），按创建顺序。"""
    activity = db.get(Activity, int(activity_id))
    if activity is None:
        raise ApiError(4040, "活动不存在", 404)
    authz.require_activity_view(db, current_user, activity)
    payload = _activity_payload(db, activity)
    # 树中只保留可见任务；``progress`` 的服务端统计口径不变
    payload["tasks"] = _visible_activity_tasks(db, activity, current_user)
    return ok(ActivityDetailOut.model_validate(payload).model_dump())


@router.post("")
def create_activity(
    payload: ActivityCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """创建活动：标题去空白后不得为空；``org_id`` 必须属于本人可管理的组织。"""
    title = (payload.title or "").strip()
    if not title:
        raise ApiError(4001, "活动标题不能为空")

    org_id = authz.resolve_task_org(
        db,
        user=current_user,
        parent=None,
        activity=None,
        org_id=payload.org_id,
    )

    activity = Activity(
        title=title,
        description=payload.description,
        location=payload.location,
        start_time=payload.start_time,
        deadline=payload.deadline,
        owner_id=int(current_user.id),
        org=payload.org,
        org_id=org_id,
        status="published",
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return ok(ActivityOut.model_validate(_activity_payload(db, activity)).model_dump())


__all__ = ["router"]