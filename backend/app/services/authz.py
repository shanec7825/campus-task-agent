"""统一授权服务（契约 `C-AUTHZ@1`）。

组织角色、任务/活动可见与可管理规则的唯一实现。路由层只调用本模块，不重复实现角色判断。

三条贯穿全模块的约束：
- 组织归属（``org_id``）只表达归属，不替代工作层级（``parent_id`` / ``depends_on``）语义。
- ``platform_admin`` 是平台管理身份，不自动获得任何组织业务内容的可见性。
- ``org_id IS NULL`` 的资源仅按「自己发布 / 负责 / 参与 / 父亲的子任务」判定，不因组织角色扩大。
"""

from __future__ import annotations


from sqlalchemy import ColumnElement, and_, exists, or_, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Activity, OrgMember, Task, TaskApplication, TaskMember, User

ALL_ROLES: tuple[str, ...] = ("admin", "collaborator", "member")
PUBLISH_ROLES: tuple[str, ...] = ("admin", "collaborator")


def org_role(db: Session, user: User, org_id: int | None) -> str | None:
    """返回用户在某组织的角色；非成员或成员状态非 ``active`` 时返回 ``None``。"""
    if org_id is None:
        return None
    return db.execute(
        select(OrgMember.role).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
            OrgMember.status == "active",
        )
    ).scalar_one_or_none()


def org_ids_for(
    db: Session,
    user: User,
    roles: tuple[str, ...] = ("admin", "collaborator", "member"),
) -> list[int]:
    """返回用户在给定角色集合中、状态为 ``active`` 的组织 ID。"""
    if not roles:
        return []
    rows = db.execute(
        select(OrgMember.org_id)
        .where(
            OrgMember.user_id == user.id,
            OrgMember.status == "active",
            OrgMember.role.in_(tuple(roles)),
        )
        .distinct()
    ).scalars()
    return [int(org_id) for org_id in rows]


def _org_role_exists(task_column, user_id: int, role: str) -> ColumnElement[bool]:
    """关联外层的 ``Task.org_id`` 的 EXISTS 子查询：用户在该任务是组织里拥有 ``role``。"""
    return exists().where(
        OrgMember.org_id == task_column,
        OrgMember.user_id == user_id,
        OrgMember.status == "active",
        OrgMember.role == role,
    )


def _self_visible_condition(task, user: User) -> ColumnElement[bool]:
    """任务自身的可见条件（不含「父任务可见则子任务可见」的继承规则）。"""
    member_open = and_(
        _org_role_exists(task.org_id, user.id, "member"),
        task.claim_type == "open",
        task.status != "cancelled",
    )
    return or_(
        task.publisher_id == user.id,
        task.assignee_id == user.id,
        exists().where(TaskMember.task_id == task.id, TaskMember.user_id == user.id),
        exists().where(TaskApplication.task_id == task.id, TaskApplication.user_id == user.id),
        _org_role_exists(task.org_id, user.id, "admin"),
        member_open,
    )


def visible_task_filter(db: Session, user: User) -> ColumnElement[bool]:
    """任务可见范围的 SQL 条件（供列表查询直接 ``where`` 使用）。

    以递归 CTE 取「自身可见」的任务及其全部后代的 ID；祖先可见则后代可见，
    因此深层子任务同样落在可见集合内，且不必把全表取回后在 Python 过滤。
    """
    anchor = select(Task.id.label("id")).where(_self_visible_condition(Task, user))
    visible = anchor.cte("visible_task_ids", recursive=True)
    descendant = select(Task.id).where(Task.parent_id == visible.c.id)
    visible = visible.union_all(descendant)
    return Task.id.in_(select(visible.c.id))


def can_view_task(db: Session, user: User, task: Task) -> bool:
    if task.id is None:
        return False
    row = db.execute(
        select(Task.id).where(Task.id == task.id, visible_task_filter(db, user)).limit(1)
    ).first()
    return row is not None


def require_task_view(db: Session, user: User, task: Task) -> None:
    if not can_view_task(db, user, task):
        # 不可见与不存在返回同一响应，不泄露资源存在性。
        raise ApiError(4040, "任务不存在", 404)


def _activity_owner_id(db: Session, activity_id: int) -> int | None:
    return db.execute(select(Activity.owner_id).where(Activity.id == activity_id)).scalar_one_or_none()


def can_manage_task(db: Session, user: User, task: Task) -> bool:
    if task.publisher_id == user.id or task.assignee_id == user.id:
        return True
    if task.org_id is not None and org_role(db, user, task.org_id) == "admin":
        return True
    if task.activity_id is not None and _activity_owner_id(db, task.activity_id) == user.id:
        return True
    return False


def require_task_manage(db: Session, user: User, task: Task) -> None:
    if not can_manage_task(db, user, task):
        raise ApiError(4030, "无权操作该任务", 403)


def can_view_activity(db: Session, user: User, activity: Activity) -> bool:
    if activity.owner_id == user.id:
        return True
    if activity.org_id is not None and org_role(db, user, activity.org_id) == "admin":
        return True
    row = db.execute(
        select(Task.id)
        .where(Task.activity_id == activity.id, visible_task_filter(db, user))
        .limit(1)
    ).first()
    return row is not None


def require_activity_view(db: Session, user: User, activity: Activity) -> None:
    if not can_view_activity(db, user, activity):
        raise ApiError(4040, "活动不存在", 404)


def can_manage_activity(db: Session, user: User, activity: Activity) -> bool:
    if activity.owner_id == user.id:
        return True
    return activity.org_id is not None and org_role(db, user, activity.org_id) == "admin"


def require_activity_manage(db: Session, user: User, activity: Activity) -> None:
    if not can_manage_activity(db, user, activity):
        raise ApiError(4030, "无权操作该活动", 403)


def resolve_task_org(
    db: Session,
    *,
    parent: Task | None,
    activity: Activity | None,
    org_id: int | None,
    user: User,
    task: Task | None = None,
) -> int | None:
    """计算任务落库时使用的 ``org_id``。

    ``parent`` / ``activity`` 未显式给出时，从 ``task`` 的既有归属补齐，便于 PATCH 场景只传 ``task``。
    最终归属（无论派生还是显式）都必须属于用户 ``admin|collaborator`` 的组织，
    派生路径不得绕过该校验。
    """
    if task is not None:
        if parent is None and task.parent_id is not None:
            parent = db.get(Task, task.parent_id)
        if activity is None and task.activity_id is not None:
            activity = db.get(Activity, task.activity_id)

    resolved: int | None
    if parent is not None:
        if org_id is not None and org_id != parent.org_id:
            raise ApiError(4001, "子任务必须与父任务属于同一组织")
        resolved = parent.org_id
    elif activity is not None:
        if org_id is not None and org_id != activity.org_id:
            raise ApiError(4001, "任务必须与所属活动属于同一组织")
        resolved = activity.org_id
    else:
        resolved = org_id

    if resolved is not None and org_role(db, user, resolved) not in PUBLISH_ROLES:
        raise ApiError(4030, "无权在该组织下创建事务", 403)
    return resolved


__all__ = [
    "ALL_ROLES",
    "PUBLISH_ROLES",
    "org_role",
    "org_ids_for",
    "visible_task_filter",
    "can_view_task",
    "require_task_view",
    "can_manage_task",
    "require_task_manage",
    "can_view_activity",
    "require_activity_view",
    "can_manage_activity",
    "require_activity_manage",
    "resolve_task_org",
]