"""资料库服务（契约 `C-RESOURCE@1`）。

职责边界：

* 资料归属（活动 / 任务 / 组织）只表达所属范围，不替代任务工作层级；
* 创建与更新权限统一复用 ``authz``，不在路由重复判断；
* 检索先在数据库内做可见性过滤，再对结果做关键词打分，禁止取全表后在 Python 过滤；
* 同一 ``resource_key`` 追加新版本，旧版本保留，归属不允许跨范围搬移。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Activity, ActivityResource, OrgMember, Task, User
from app.schemas import ResourceCreateIn, ResourceOut
from app.services import authz, kb_service

ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040

MAX_LIMIT = 50
DEFAULT_LIMIT = 20


def _approval_org_ids(db: Session, user: User) -> list[int]:
    return authz.org_ids_for(db, user, ("admin", "collaborator"))


def visible_resource_filter(db: Session, user: User):
    """资料可见范围 SQL 条件（`C-RESOURCE@1`）。

    可见 = 绑定任务对我可见 | 绑定活动对我可见 | 仅组织资源属于我所在组织或由我创建。
    """
    visible_tasks = (
        select(Task.id.label("task_id"), Task.activity_id.label("activity_id"))
        .where(authz.visible_task_filter(db, user))
        .subquery()
    )
    admin_org_ids = authz.org_ids_for(db, user, ("admin",))
    member_org_ids = authz.org_ids_for(db, user)
    task_visible = ActivityResource.task_id.in_(select(visible_tasks.c.task_id))
    activity_visible = or_(
        exists().where(
            Activity.id == ActivityResource.activity_id,
            Activity.owner_id == user.id,
        ),
        and_(
            ActivityResource.activity_id.is_not(None),
            ActivityResource.task_id.is_(None),
            exists().where(
                Activity.id == ActivityResource.activity_id,
                Activity.org_id.in_(admin_org_ids),
            ),
        ),
        exists().where(visible_tasks.c.activity_id == ActivityResource.activity_id),
    )
    org_only_visible = and_(
        ActivityResource.task_id.is_(None),
        ActivityResource.activity_id.is_(None),
        or_(
            ActivityResource.org_id.in_(member_org_ids),
            ActivityResource.created_by == user.id,
        ),
    )
    return or_(
        and_(ActivityResource.task_id.is_not(None), task_visible),
        and_(ActivityResource.activity_id.is_not(None), activity_visible),
        org_only_visible,
    )


def _require_resource_manage(db: Session, user: User, row: ActivityResource) -> None:
    """资料更新权限：创建者、任务管理者、活动负责人或组织管理员。"""
    if int(row.created_by) == int(user.id):
        return
    if row.task_id is not None:
        task = db.get(Task, int(row.task_id))
        if task is not None and authz.can_manage_task(db, user, task):
            return
    if row.activity_id is not None:
        activity = db.get(Activity, int(row.activity_id))
        if activity is not None and authz.can_manage_activity(db, user, activity):
            return
    if row.org_id is not None and authz.org_role(db, user, int(row.org_id)) == "admin":
        return
    raise ApiError(ERR_FORBIDDEN, "无权更新该资料", 403)


def _latest_for_key(db: Session, resource_key: str) -> ActivityResource | None:
    return db.execute(
        select(ActivityResource)
        .where(ActivityResource.resource_key == resource_key)
        .order_by(ActivityResource.version.desc(), ActivityResource.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def create_resource(db: Session, user: User, payload: ResourceCreateIn) -> ActivityResource:
    """新增资料或为已有 ``resource_key`` 追加新版本（只 flush，不 commit）。"""
    task: Task | None = None
    activity: Activity | None = None
    org_id = payload.org_id

    if payload.task_id is not None:
        task = db.get(Task, int(payload.task_id))
        if task is None:
            raise ApiError(ERR_NOT_FOUND, "任务不存在", 404)
        authz.require_task_view(db, user, task)
        authz.require_task_manage(db, user, task)
        if payload.activity_id is not None and payload.activity_id != task.activity_id:
            raise ApiError(ERR_INVALID_PARAM, "资料任务与所属活动不一致")
        if org_id is not None and org_id != task.org_id:
            raise ApiError(ERR_INVALID_PARAM, "资料任务与组织归属不一致")
        activity_id = task.activity_id
        org_id = task.org_id
    elif payload.activity_id is not None:
        activity = db.get(Activity, int(payload.activity_id))
        if activity is None:
            raise ApiError(ERR_NOT_FOUND, "活动不存在", 404)
        authz.require_activity_view(db, user, activity)
        authz.require_activity_manage(db, user, activity)
        if org_id is not None and org_id != activity.org_id:
            raise ApiError(ERR_INVALID_PARAM, "资料活动与组织归属不一致")
        activity_id = activity.id
        org_id = activity.org_id
    else:
        activity_id = None
        if org_id is None:
            raise ApiError(ERR_INVALID_PARAM, "资料必须归属活动、任务或组织")
        if authz.org_role(db, user, int(org_id)) not in authz.PUBLISH_ROLES:
            raise ApiError(ERR_FORBIDDEN, "无权在该组织创建资料", 403)

    title = payload.title.strip()
    url = payload.url.strip()
    summary = (payload.summary or "").strip() or None
    if not title or not url:
        raise ApiError(ERR_INVALID_PARAM, "资料标题与链接不能为空")
    if not url.lower().startswith(("http://", "https://")):
        raise ApiError(ERR_INVALID_PARAM, "资料链接必须是 http 或 https 地址")

    resource_key = (payload.resource_key or "").strip()
    version = 1
    if resource_key:
        latest = _latest_for_key(db, resource_key)
        if latest is not None:
            _require_resource_manage(db, user, latest)
            if (
                latest.activity_id != activity_id
                or latest.task_id != payload.task_id
                or latest.org_id != org_id
            ):
                raise ApiError(ERR_INVALID_PARAM, "资料新版本不能改变归属范围")
            version = int(latest.version) + 1
    else:
        resource_key = f"res-{uuid.uuid4().hex}"

    row = ActivityResource(
        resource_key=resource_key,
        activity_id=activity_id,
        task_id=payload.task_id,
        org_id=org_id,
        title=title,
        summary=summary,
        resource_type=payload.resource_type,
        url=url,
        version=version,
        created_by=int(user.id),
    )
    db.add(row)
    db.flush()
    return row


def _norm(text: str | None) -> str:
    """检索归一化：小写、去空白（与知识库同口径，但不依赖其私有函数）。"""
    return "".join((text or "").lower().split())


def _score(query: str, row: ActivityResource) -> float:
    """与知识库同口径的关键词相似度（标题 + 摘要）。"""
    q_tokens = set(kb_service.tokenize(query))
    text = f"{row.title or ''} {row.summary or ''}"
    text_tokens = set(kb_service.tokenize(text))
    intersection = len(q_tokens & text_tokens)
    union = max(1, len(q_tokens | text_tokens))
    jaccard = intersection / union
    q_norm = _norm(query)
    text_norm = _norm(text)
    contain = 1.0 if (q_norm and text_norm and (q_norm in text_norm or text_norm in q_norm)) else 0.0
    return round(0.7 * jaccard + 0.3 * contain, 4)


def _related_condition(task: Task):
    """任务详情「相关资料」范围：同活动 + 同组织其他活动（往期）。"""
    conditions = [ActivityResource.task_id == task.id]
    if task.activity_id is not None:
        conditions.append(ActivityResource.activity_id == task.activity_id)
    if task.org_id is not None:
        conditions.append(
            and_(
                ActivityResource.org_id == task.org_id,
                ActivityResource.activity_id.is_not(None),
                ActivityResource.activity_id != task.activity_id,
            )
        )
    return or_(*conditions)


def list_resources(
    db: Session,
    user: User,
    *,
    query: str = "",
    activity_id: int | None = None,
    task_id: int | None = None,
    related_task_id: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[ResourceOut]:
    """按权限检索资料；无关键词时按更新时间倒序。"""
    bounded = max(1, min(int(limit), MAX_LIMIT))
    sql = select(ActivityResource).where(visible_resource_filter(db, user))

    if related_task_id is not None:
        task = db.get(Task, int(related_task_id))
        if task is None:
            raise ApiError(ERR_NOT_FOUND, "任务不存在", 404)
        authz.require_task_view(db, user, task)
        sql = sql.where(_related_condition(task))
    if activity_id is not None:
        sql = sql.where(ActivityResource.activity_id == int(activity_id))
    if task_id is not None:
        sql = sql.where(ActivityResource.task_id == int(task_id))

    rows: Sequence[ActivityResource] = db.execute(
        sql.order_by(ActivityResource.created_at.desc(), ActivityResource.id.desc())
    ).scalars().all()

    text = (query or "").strip()
    if text:
        scored = [(_score(text, row), row) for row in rows]
        scored = [(score, row) for score, row in scored if score > 0]
        scored.sort(key=lambda item: (item[0], int(item[1].id)), reverse=True)
        rows = [row for _, row in scored]

    rows = rows[:bounded]
    return _payload(db, rows)


def latest_resource_versions(db: Session, user: User, task: Task, limit: int = 5) -> list[ResourceOut]:
    """预审引用：当前任务可用的最新资料版本（只看每 key 的最新版本）。"""
    rows = list_resources(db, user, related_task_id=int(task.id), limit=MAX_LIMIT)
    latest_by_key: dict[str, ResourceOut] = {}
    for row in rows:
        current = latest_by_key.get(row.resource_key)
        if current is None or row.version > current.version:
            latest_by_key[row.resource_key] = row
    ordered = sorted(latest_by_key.values(), key=lambda row: row.version, reverse=True)
    return ordered[: max(1, limit)]


def _payload(db: Session, rows: Sequence[ActivityResource]) -> list[ResourceOut]:
    if not rows:
        return []
    activity_ids = sorted({int(row.activity_id) for row in rows if row.activity_id is not None})
    user_ids = sorted({int(row.created_by) for row in rows})
    activities: dict[int, str] = {}
    if activity_ids:
        activities = {
            int(activity.id): activity.title
            for activity in db.execute(
                select(Activity).where(Activity.id.in_(activity_ids))
            ).scalars().all()
        }
    users: dict[int, str] = {
        int(user.id): user.display_name
        for user in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    }
    return [
        ResourceOut(
            id=int(row.id),
            resource_key=row.resource_key,
            activity_id=row.activity_id,
            task_id=row.task_id,
            org_id=row.org_id,
            activity_title=activities.get(int(row.activity_id)) if row.activity_id is not None else None,
            title=row.title,
            summary=row.summary,
            resource_type=row.resource_type,
            url=row.url,
            version=int(row.version),
            created_by=int(row.created_by),
            created_by_name=users.get(int(row.created_by), ""),
            created_at=row.created_at,
        )
        for row in rows
    ]


def to_out(db: Session, rows: Sequence[ActivityResource]) -> list[ResourceOut]:
    """公开序列化入口：路由与测试复用同一份字段映射。"""
    return _payload(db, rows)


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "create_resource",
    "latest_resource_versions",
    "list_resources",
    "to_out",
    "visible_resource_filter",
]