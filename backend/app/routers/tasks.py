"""任务路由（契约 `C-TASKS@1` / `C-TASK-API@1`，owner = T2）。

错误码总表在本模块（计划 `2.2.4`），其他路由（``checkin``）复用同一份常量。
状态机流转集合由 ``services/task_state.py`` 提供（全后端唯一实现），本模块的
:func:`_ensure_transition` 是所有手工状态变更前的统一校验入口，非法流转统一
``ApiError(4090, "任务当前状态不允许该操作")``，且**先校验后写库**。

逐人执行语义（`C-MEMBER@1`）：进度 / 提交 / 验收均以 ``task_members`` 行为粒度，
任务级 ``status`` 由 :func:`member_service.sync_task_status` 按成员状态派生。

写库顺序约束（实现要点 2）：单请求内最多保留一次业务 ``commit``；
``verify`` 的「任务状态 + 成员状态 + 积分流水 + 用户余额 + 通知」在同一事务内提交。
"""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime
from typing import Any, Iterable, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf
from app.errors import ApiError, ok
from app.models import Activity, ProgressLog, Task, TaskApplication, TaskDependency, User
from app.schemas import (
    ACCEPTANCE_KEY,
    AssignIn,
    Draft,
    ProgressIn,
    ProgressOut,
    SubmissionFileIn,
    SubmitIn,
    TaskBrief,
    TaskChangeDownstream,
    TaskChangeImpactOut,
    TaskChangeMember,
    TaskCreate,
    TaskDetailOut,
    TaskOut,
    TaskUpdate,
    VerifyIn,
    VerifyOut,
    normalize_acceptance,
)
from app.services import activity_service
from app.services import application_service
from app.services import authz
from app.services import credit as credit_service
from app.services import member_service, notify_service
from app.services import submission_service
from app.services import task_graph_service
from app.services.task_state import ALLOWED_TRANSITIONS

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(require_csrf)]
)

# --------------------------------------------------------------------------- #
# 错误码总表（计划 `2.2.4`，全后端唯一实现位置）
# --------------------------------------------------------------------------- #
ERR_INVALID_PARAM = 4001  # 参数校验失败
ERR_UNAUTHORIZED = 4010  # 未登录
ERR_DEPENDENCY = 4020  # 前置依赖未完成
ERR_FORBIDDEN = 4030  # 权限不足
ERR_NOT_FOUND = 4040  # 资源不存在
ERR_CONFLICT = 4090  # 状态冲突

# --------------------------------------------------------------------------- #
# 状态机（R3-AC1）：合法流转集合由 `services/task_state.py` 定义，
# 本模块只做写库前校验；前端只做展示与置灰。
# --------------------------------------------------------------------------- #

# 允许指派的源状态（`2.2.4` 指派规则）
ASSIGN_ALLOWED_STATUSES: frozenset[str] = frozenset({"published", "claimed"})

# PATCH 允许修改的列（`2.2.4` 修改规则；parent_id 不在白名单内）
_TASK_UPDATE_FIELDS: tuple[str, ...] = (
    "description",
    "location",
    "start_time",
    "deadline",
    "quota",
    "volunteer_hours",
    "claim_type",
    "assignee_id",
    "depends_on",
    "sop_guide",
    "style_note",
    "credit_reward",
)

# 未提供 reminder_rule 时的兜底规则（`2.2.2` 关键映射表）
DEFAULT_REMINDER_RULE: dict[str, Any] = {"days_before": 1, "day_of": True, "on_overdue": True}


def _ensure_transition(task: Task, target: str) -> None:
    """校验 ``task.status → target`` 是否合法，非法统一抛 4090（R3-AC2）。"""
    allowed = ALLOWED_TRANSITIONS.get(task.status, frozenset())
    if target not in allowed:
        logger.info("非法流转被拒绝 task_id=%s %s -> %s", task.id, task.status, target)
        raise ApiError(ERR_CONFLICT, "任务当前状态不允许该操作")


def _get_task_or_404(db: Session, task_id: int) -> Task:
    """按 id 取任务，不存在抛 4040。"""
    task = db.get(Task, task_id)
    if task is None:
        raise ApiError(ERR_NOT_FOUND, "任务不存在")
    return task


def _now_local() -> str:
    """服务器本地时间，格式与全库口径一致：``YYYY-MM-DD HH:MM:SS``。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _my_member_status(members: Iterable[dict[str, Any]], current_user_id: int) -> str | None:
    """从成员载荷里取「当前用户」的成员状态；非 approved 成员返回 ``None``。"""
    for item in members:
        if int(item.get("user_id", 0)) == int(current_user_id):
            return str(item.get("status") or member_service.MEMBER_NOT_STARTED)
    return None


# --------------------------------------------------------------------------- #
# 任务序列化（TaskOut / TaskDetailOut 的派生字段计算）
# --------------------------------------------------------------------------- #
def _names_map(db: Session, tasks: Iterable[Task]) -> dict[int, str]:
    """批量取 ``user_id -> display_name``，避免逐行查询（N+1）。"""
    ids: set[int] = set()
    for task in tasks:
        ids.add(int(task.publisher_id))
        if task.assignee_id is not None:
            ids.add(int(task.assignee_id))
    if not ids:
        return {}
    rows = db.query(User.id, User.display_name).filter(User.id.in_(ids)).all()
    return {int(row[0]): str(row[1]) for row in rows}


def _activity_titles_map(db: Session, tasks: Iterable[Task]) -> dict[int, str]:
    """批量取任务所属活动的 ``activity_id -> title``，避免逐行查询（N+1）。"""
    ids = {int(task.activity_id) for task in tasks if task.activity_id is not None}
    if not ids:
        return {}
    rows = db.query(Activity.id, Activity.title).filter(Activity.id.in_(ids)).all()
    return {int(row[0]): str(row[1]) for row in rows}


def _dep_status_map(db: Session, tasks: Iterable[Task]) -> dict[int, dict[int, str]]:
    """批量取 ``task_id -> {前置 id: status}``，供多前置 ``is_claimable`` 计算。"""
    return task_graph_service.dependency_status_bulk(db, list(tasks))


def _dependencies_verified(dep_status: dict[int, int | str] | dict[int, str] | None) -> bool:
    """所有前置都必须 ``verified``（缺失前置视为未完成）。"""
    if not dep_status:
        return True
    return all(str(status) == "verified" for status in dep_status.values())


def _is_claimable(
    task: Task,
    current_user_id: int,
    dep_status: dict[int, dict[int, str]],
    approved_count: int,
    my_status: str | None,
) -> bool:
    """`C-APPLY@1` 的可报名公式（前端置灰用，真正校验以后端 A1 六条顺序为准）。

    ``claim_type`` 不再参与判定（``assign`` 任务同样可被学生报名，由发布者决定）。
    多前置（`C-TASK-GRAPH@1`）必须全部 ``verified``。
    """
    if str(task.status) not in ("published", "claimed"):
        return False
    if task.quota is not None and int(approved_count) >= int(task.quota):
        return False
    if int(task.publisher_id) == int(current_user_id):
        return False
    if not _dependencies_verified(dep_status.get(int(task.id))):
        return False
    return my_status not in application_service.BLOCKING_STATUSES


def _my_status_map(
    db: Session,
    tasks: Iterable[Task],
    current_user_id: int,
    approved_names: dict[int, list[tuple[int, str]]],
) -> dict[int, str | None]:
    """批量取 ``task_id -> 当前用户的报名状态``（一次 IN 查询，禁止 N+1）。

    legacy 回退与 ``application_service.user_application_status`` 保持一致：
    无报名行但本人是 ``assignee_id`` 且该任务尚无 approved 行时视为 ``approved``；
    该条件等价于「``approved_users_bulk`` 的结果里含本人」。
    """
    task_ids = [int(task.id) for task in tasks if task.id is not None]
    if not task_ids:
        return {}

    rows = (
        db.query(TaskApplication.task_id, TaskApplication.status)
        .filter(
            TaskApplication.user_id == int(current_user_id),
            TaskApplication.task_id.in_(task_ids),
        )
        .all()
    )
    own: dict[int, str] = {int(row[0]): str(row[1]) for row in rows}

    result: dict[int, str | None] = {}
    for task in tasks:
        task_id = int(task.id)
        status = own.get(task_id)
        if status is None:
            approved_pairs = approved_names.get(task_id) or []
            if any(int(user_id) == int(current_user_id) for user_id, _ in approved_pairs):
                status = application_service.APPROVED
        result[task_id] = status
    return result


def _task_payload(
    task: Task,
    names: dict[int, str],
    dep_status: dict[int, dict[int, str]],
    current_user_id: int,
    *,
    approved_names: dict[int, list[tuple[int, str]]],
    counts: dict[str, int],
    my_status: str | None,
    members: list[dict[str, Any]] | None = None,
    my_member_status: str | None = None,
    activity_titles: dict[int, str] | None = None,
) -> dict[str, Any]:
    """构造与 ``TaskOut`` 完全对齐的字典（含报名派生字段与逐人成员载荷）。

    Args:
        task: 任务实体。
        names: ``user_id -> display_name`` 映射（发布者名称）。
        dep_status: 前置任务 ``task_id -> {depends_on_id: status}`` 映射。
        current_user_id: 当前用户（用于 ``is_claimable`` 与本人状态）。
        approved_names: ``task_id -> [(user_id, display_name)]``（含 legacy 回退）。
        counts: ``{"pending": n, "approved": m}``（含 legacy 回退）。
        my_status: 当前用户对该任务的报名状态（无记录为 ``None``）。
        members: ``task.members`` 载荷（逐人执行状态）。
        my_member_status: 当前用户的成员状态（非成员为 ``None``）。
        activity_titles: ``activity_id -> title`` 映射（批量解析，无活动为空字典）。
    """
    task_id = int(task.id)
    assignee_names = [str(name) for _, name in (approved_names.get(task_id) or [])]
    applied_count = int(counts.get(application_service.PENDING, 0))
    approved_count = int(counts.get(application_service.APPROVED, 0))
    activity_id = int(task.activity_id) if task.activity_id is not None else None
    activity_title = (activity_titles or {}).get(activity_id) if activity_id is not None else None

    raw: dict[str, Any] = {
        "id": task.id,
        "parent_id": task.parent_id,
        "activity_id": activity_id,
        "org_id": task.org_id,
        "title": task.title,
        "description": task.description,
        "location": task.location,
        "start_time": task.start_time,
        "deadline": task.deadline,
        "quota": task.quota,
        "volunteer_hours": task.volunteer_hours,
        "status": task.status,
        "claim_type": task.claim_type,
        "publisher_id": task.publisher_id,
        "assignee_id": task.assignee_id,
        "depends_on": task.depends_on,
        "depends_on_ids": list((dep_status.get(task_id) or {}).keys()),
        "sop_guide": task.sop_guide,
        "style_note": task.style_note,
        "extras": task.extras or {},
        "reminder_rule": task.reminder_rule,
        "credit_reward": task.credit_reward,
        "created_at": task.created_at,
        # 首位 approved 兼容字段（`C-APPLY@1` 多负责人规则表）
        "assignee_name": assignee_names[0] if assignee_names else None,
        "publisher_name": names.get(int(task.publisher_id), ""),
        "is_claimable": _is_claimable(
            task, current_user_id, dep_status, approved_count, my_status
        ),
        "applied_count": applied_count,
        "approved_count": approved_count,
        "my_application_status": my_status,
        "assignee_names": assignee_names,
        "members": members or [],
        "my_member_status": my_member_status,
    }
    payload = TaskOut.model_validate(raw).model_dump()
    # activity_title 只属于 TaskDetailOut，TaskOut 校验会丢弃，这里保留给详情响应
    payload["activity_title"] = activity_title
    return payload


def _single_task_payload(db: Session, task: Task, current_user_id: int) -> dict[str, Any]:
    """单个任务的序列化入口：批量 approved / 计数 / 本人状态 / 成员载荷各一次查询。"""
    approved_names = application_service.approved_users_bulk(db, [task])
    counts = application_service.status_counts_bulk(db, [int(task.id)])
    my_status = _my_status_map(db, [task], current_user_id, approved_names).get(int(task.id))
    members = member_service.members_payload_bulk(db, [task]).get(int(task.id), [])
    return _task_payload(
        task,
        _names_map(db, [task]),
        _dep_status_map(db, [task]),
        current_user_id,
        approved_names=approved_names,
        counts=counts.get(int(task.id), {}),
        my_status=my_status,
        members=members,
        my_member_status=_my_member_status(members, current_user_id),
        activity_titles=_activity_titles_map(db, [task]),
    )


def _merge_dependency_ids(
    depends_on: int | None, depends_on_ids: list[int] | None
) -> list[int]:
    """选择本次请求的依赖集合（`C-TASK-GRAPH@1`）。

    显式 ``depends_on_ids`` **覆盖**旧单前置字段（即使同时传了 ``depends_on``）；
    只在未提供新字段时回退到旧 ``depends_on``。保留原始输入（含重复项），
    重复校验由 ``task_graph_service`` 统一完成；路由层静默去重会把用户错误变成“成功”。
    """
    if depends_on_ids is not None:
        return [int(item) for item in depends_on_ids]
    return [int(depends_on)] if depends_on is not None else []


# --------------------------------------------------------------------------- #
# 知识库入库（T3 提供实现；本任务只负责调用，失败不得回滚任务发布）
# --------------------------------------------------------------------------- #
def _index_task_safe(db: Session, task: Task) -> None:
    """调用 ``kb_service.index_task``（`C-KB@1`），失败只记日志。

    T3 尚未交付时该函数仍为 ``NotImplementedError`` 桩，因此这里捕获全部异常；
    任务发布本身已在调用前提交，任何入库失败都不会回滚已发布的任务。
    """
    task_id = task.id
    try:
        # 延迟导入：T3 交付前也能正常启动（模块级导入会让发布流程在启动期失败）
        from app.services.kb_service import index_task

        index_task(db, task)
        db.commit()
    except Exception:
        logger.warning("知识库入库失败（不影响任务发布）task_id=%s", task_id, exc_info=True)
        try:
            db.rollback()
        except Exception:  # rollback 本身失败时保持原状，绝不向上冒泡
            logger.warning("知识库入库失败后 rollback 异常 task_id=%s", task_id, exc_info=True)


# --------------------------------------------------------------------------- #
# #1 列表
# --------------------------------------------------------------------------- #
@router.get("")
def list_tasks(
    status: str | None = Query(default=None, description="单值过滤；逗号分隔按 IN 处理"),
    scope: Literal["all", "mine"] = Query(default="all"),
    include_sub: bool = Query(default=False),
    activity_id: int | None = Query(default=None, description="按所属活动过滤"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """任务列表：状态 / 范围 / 是否含子任务 / 所属活动过滤，``created_at DESC, id DESC`` 排序。

    ``scope=mine`` 的语义（多负责人模型）：我是发布者 **或** 我是任一 approved 成员
    **或** （legacy）``tasks.assignee_id == 我``；``scope=all`` 行为不变。

    可见性（`C-TASK-ORG@1`）：根条件先叠加 ``authz.visible_task_filter``，
    列表永不返回不可见任务；``scope=mine`` 在其上再叠加「我的」条件。
    """
    query = db.query(Task).filter(authz.visible_task_filter(db, current_user))

    if status:
        values = [item.strip() for item in status.split(",") if item.strip()]
        if values:
            query = query.filter(Task.status.in_(values))

    if activity_id is not None:
        query = query.filter(Task.activity_id == activity_id)

    if scope == "mine":
        # 与活动范围共用同一条件；不能只看 assignee_id（首位 approved 兼容字段）
        query = query.filter(authz.my_task_condition(db, current_user))

    if not include_sub:
        query = query.filter(Task.parent_id.is_(None))

    tasks = query.order_by(Task.created_at.desc(), Task.id.desc()).all()

    # 批量派生（整页一次）：approved 成员 / 状态计数 / 本人状态 / 成员载荷，禁止循环查库
    names = _names_map(db, tasks)
    dep_status = _dep_status_map(db, tasks)
    approved_names = application_service.approved_users_bulk(db, tasks)
    counts = application_service.status_counts_bulk(db, tasks)
    my_status = _my_status_map(db, tasks, current_user.id, approved_names)
    members_by_task = member_service.members_payload_bulk(db, tasks)
    activity_titles = _activity_titles_map(db, tasks)
    items = []
    for task in tasks:
        members = members_by_task.get(int(task.id), [])
        items.append(
            _task_payload(
                task,
                names,
                dep_status,
                current_user.id,
                approved_names=approved_names,
                counts=counts.get(int(task.id), {}),
                my_status=my_status.get(int(task.id)),
                members=members,
                my_member_status=_my_member_status(members, current_user.id),
                activity_titles=activity_titles,
            )
        )
    return ok({"items": items})


# --------------------------------------------------------------------------- #
# #2 发布
# --------------------------------------------------------------------------- #
@router.post("")
def create_task(
    payload: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """发布任务（手动兜底，R2.1-AC1）；成功后调用知识库增量入库。"""
    title = payload.title.strip()
    if not title:
        raise ApiError(ERR_INVALID_PARAM, "任务标题不能为空")
    if payload.quota is not None and payload.quota < 1:
        raise ApiError(ERR_INVALID_PARAM, "需求人数必须大于 0")
    if payload.credit_reward is not None and payload.credit_reward < 0:
        raise ApiError(ERR_INVALID_PARAM, "完成奖励积分不能为负数")

    # 成果提交策略（`C-SUBMISSION-POLICY@1`）：写库前校验，非法 4001 且无写入
    extras = normalize_acceptance(payload.extras)

    # 子任务：发布者必须与父任务一致（`2.2.4` 发布规则）
    parent: Task | None = None
    if payload.parent_id is not None:
        parent = db.get(Task, payload.parent_id)
        if parent is None:
            raise ApiError(ERR_INVALID_PARAM, "父任务不存在")
        if int(parent.publisher_id) != int(current_user.id):
            raise ApiError(ERR_FORBIDDEN, "只能在自己的任务下创建子任务")

    # 活动归属与三层 / 跨活动校验（唯一实现；调用发生在 db.add 之前，失败无写入）
    activity_id = activity_service.resolve_task_placement(
        db,
        parent=parent,
        activity_id=payload.activity_id,
    )

    # 组织归属（`C-TASK-ORG@1`）：子任务继承父任务，隶属活动的任务继承活动组织；
    # 显式 org_id 必须属于本人 admin|collaborator 的组织（4030 / 4001 由 authz 判定）
    activity = db.get(Activity, int(activity_id)) if activity_id is not None else None
    org_id = authz.resolve_task_org(
        db,
        user=current_user,
        parent=parent,
        activity=activity,
        org_id=payload.org_id,
    )

    # 依赖：多前置（`C-TASK-GRAPH@1`）统一在写库前校验，失败无写入
    dependency_ids = task_graph_service.validate_dependencies(
        db,
        task_id=None,
        parent_id=payload.parent_id,
        activity_id=activity_id,
        org_id=org_id,
        depends_on_ids=_merge_dependency_ids(payload.depends_on, payload.depends_on_ids),
    )

    # 指派：仅 claim_type=assign 且提供 assignee_id 时生效，状态直接置 claimed
    assignee_id: int | None = None
    task_status = "published"
    if payload.claim_type == "assign" and payload.assignee_id is not None:
        if int(payload.assignee_id) == int(current_user.id):
            raise ApiError(ERR_FORBIDDEN, "不能指派自己")
        if db.get(User, payload.assignee_id) is None:
            raise ApiError(ERR_INVALID_PARAM, "指派的用户不存在")
        assignee_id = int(payload.assignee_id)
        task_status = "claimed"

    reminder_rule = (
        payload.reminder_rule.model_dump() if payload.reminder_rule is not None else dict(DEFAULT_REMINDER_RULE)
    )

    task = Task(
        parent_id=payload.parent_id,
        activity_id=activity_id,
        org_id=org_id,
        title=title,
        description=payload.description,
        location=payload.location,
        start_time=payload.start_time,
        deadline=payload.deadline,
        quota=payload.quota,
        volunteer_hours=payload.volunteer_hours,
        status=task_status,
        claim_type=payload.claim_type,
        publisher_id=current_user.id,
        assignee_id=assignee_id,
        depends_on=dependency_ids[0] if dependency_ids else None,
        sop_guide=payload.sop_guide,
        style_note=payload.style_note,
        extras=extras,
        reminder_rule=reminder_rule,
        credit_reward=payload.credit_reward,
    )
    db.add(task)
    db.flush()

    # 依赖边表与旧 depends_on 同步为同一集合（多前置；空集合不写边）
    if dependency_ids:
        task_graph_service.replace_dependencies(db, task, dependency_ids)

    # 直接指派：同一事务内补齐 approved 报名行与 not_started 成员行（`C-TASK-API@1`）
    if assignee_id is not None:
        now = _now_local()
        db.add(
            TaskApplication(
                task_id=int(task.id),
                user_id=int(assignee_id),
                status=application_service.APPROVED,
                reason=None,
                created_at=now,
                decided_at=now,
                decided_by=int(current_user.id),
            )
        )
        member_service.ensure_member(db, task, int(assignee_id))

    db.commit()
    db.refresh(task)

    # 先固化响应快照（后续知识库入库失败可能 rollback 使 ORM 对象过期）
    data = _single_task_payload(db, task, current_user.id)

    if assignee_id is not None:
        notify_service.create_notification(
            db,
            user_id=assignee_id,
            task_id=task.id,
            level="info",
            title="你被指派了新任务",
            content=f"你被指派《{task.title}》，截止 {task.deadline or '未设置'}。",
        )

    _index_task_safe(db, task)
    return ok(data)


# --------------------------------------------------------------------------- #
# #3 详情
# --------------------------------------------------------------------------- #
@router.get("/{task_id}")
def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """任务详情：含子任务、进度记录与 ``sop_guide``。"""
    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)

    children = (
        db.query(Task)
        .filter(Task.parent_id == task.id)
        .order_by(Task.created_at.asc(), Task.id.asc())
        .all()
    )

    logs = (
        db.query(ProgressLog)
        .filter(ProgressLog.task_id == task.id)
        .order_by(ProgressLog.created_at.asc(), ProgressLog.id.asc())
        .all()
    )
    log_user_ids = {int(log.user_id) for log in logs}
    user_names: dict[int, str] = {}
    if log_user_ids:
        rows = db.query(User.id, User.display_name).filter(User.id.in_(log_user_ids)).all()
        user_names = {int(row[0]): str(row[1]) for row in rows}

    payload = _single_task_payload(db, task, current_user.id)
    if task.parent_id is not None:
        parent_task = db.get(Task, int(task.parent_id))
        if parent_task is not None:
            payload["parent_title"] = parent_task.title

    # 直接前置 / 后继与局部图谱：只含当前用户可见任务（`C-ACTIVITY-GRAPH@1`）
    dependencies, dependents = task_graph_service.neighbor_tasks(db, task)
    visible_dependencies = [
        item for item in dependencies if authz.can_view_task(db, current_user, item)
    ]
    visible_dependents = [item for item in dependents if authz.can_view_task(db, current_user, item)]
    brief_tasks = [*visible_dependencies, *visible_dependents, *children]
    brief_dependency_ids = task_graph_service.dependency_ids_bulk(db, brief_tasks)

    def _brief_payload(item: Task) -> dict[str, Any]:
        data = TaskBrief.model_validate(item).model_dump()
        data["depends_on_ids"] = brief_dependency_ids.get(int(item.id), [])
        return data

    payload["dependencies"] = [_brief_payload(item) for item in visible_dependencies]
    payload["dependents"] = [_brief_payload(item) for item in visible_dependents]
    graph_tasks = [task, *visible_dependencies, *visible_dependents]
    payload["graph"] = task_graph_service.build_graph_payload(
        db, graph_tasks, {int(item.id) for item in graph_tasks}
    )

    payload["children"] = [_brief_payload(child) for child in children]
    payload["progress"] = [
        ProgressOut.model_validate(
            {
                "id": log.id,
                "task_id": log.task_id,
                "user_id": log.user_id,
                "user_name": user_names.get(int(log.user_id), ""),
                "content": log.content,
                "created_at": log.created_at,
            }
        ).model_dump()
        for log in logs
    ]
    return ok(TaskDetailOut.model_validate(payload).model_dump())


# --------------------------------------------------------------------------- #
# #3.5 改期影响预览（契约 `C-TASK-CHANGE-API@1`）
# --------------------------------------------------------------------------- #
def _change_downstream_tasks(db: Session, task_id: int, viewer: User) -> list[Task]:
    """取依赖当前任务且对查看者可见的后续任务。"""
    return list(
        db.execute(
            select(Task)
            .join(TaskDependency, TaskDependency.task_id == Task.id)
            .where(
                TaskDependency.depends_on_id == int(task_id),
                authz.visible_task_filter(db, viewer),
            )
            .order_by(Task.id.asc())
        ).scalars()
    )


def _change_recipients(db: Session, task: Task) -> list[int]:
    """变更通知接收人：发布者 + 当前 approved 成员（去重、升序）。"""
    members = member_service.effective_members(db, task)
    return sorted({int(task.publisher_id), *[int(member.user_id) for member in members]})


def _change_impact_payload(
    db: Session, task: Task, proposed_deadline: str | None, viewer: User
) -> dict[str, Any]:
    downstream = _change_downstream_tasks(db, int(task.id), viewer)
    members = member_service.effective_members(db, task)
    return TaskChangeImpactOut(
        task_id=int(task.id),
        title=task.title,
        current_deadline=task.deadline,
        proposed_deadline=proposed_deadline,
        # 以归一化时间比较，避免同一时刻不同写法被误判为改期。
        reminders_reset=(
            notify_service.deadline_version(proposed_deadline)
            != notify_service.deadline_version(task.deadline)
        ),
        affected_members=[
            TaskChangeMember(id=int(member.user_id), name=member.user_name) for member in members
        ],
        downstream_tasks=[TaskChangeDownstream.model_validate(item) for item in downstream],
        notified_user_ids=_change_recipients(db, task),
    ).model_dump()


@router.get("/{task_id}/change-impact")
def get_task_change_impact(
    task_id: int,
    deadline: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """只读预览改期影响；``deadline`` 缺省/空串表示清除截止时间。"""
    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)
    authz.require_task_manage(db, current_user, task)

    proposed = (deadline or "").strip() or None
    if proposed is not None and notify_service.deadline_version(proposed) is None:
        raise ApiError(ERR_INVALID_PARAM, "截止时间格式无效")
    return ok(_change_impact_payload(db, task, proposed, current_user))


# --------------------------------------------------------------------------- #
# #4 修改
# --------------------------------------------------------------------------- #
@router.patch("/{task_id}")
def patch_task(
    task_id: int,
    payload: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """修改任务：省略字段 = 不修改；显式 ``null`` = 清空该列。

    ``extras`` 为合并语义：请求中的键值覆盖同名字段、其它键保留（``extras={}`` 不再
    清空对象）；``acceptance`` 显式传 ``null`` 时删除该键、其它键保留。
    """
    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)
    authz.require_task_manage(db, current_user, task)

    # 变更副作用需要旧值（`C-TASK-CHANGE@1`）；在任何字段写入前记录。
    old_deadline = task.deadline
    old_status = task.status

    provided = payload.model_fields_set

    # 空串按“清除截止”处理，与影响预览的缺省语义一致（审查第二轮 S2）。
    if "deadline" in provided and isinstance(payload.deadline, str) and not payload.deadline.strip():
        payload.deadline = None

    # 活动归属与层级校验：仅显式提供 parent_id / activity_id 时执行（唯一实现）
    if "parent_id" in provided or "activity_id" in provided:
        parent: Task | None = None
        if "parent_id" in provided and payload.parent_id is not None:
            parent = db.get(Task, payload.parent_id)
            if parent is None:
                raise ApiError(ERR_INVALID_PARAM, "父任务不存在")
            if int(parent.publisher_id) != int(current_user.id):
                raise ApiError(ERR_FORBIDDEN, "只能在自己的任务下创建子任务")
        resolved_activity_id = activity_service.resolve_task_placement(
            db,
            parent=parent,
            activity_id=payload.activity_id if "activity_id" in provided else task.activity_id,
            task_id=int(task.id),
            task=task,
        )
        if "parent_id" in provided:
            task.parent_id = int(parent.id) if parent is not None else None
        task.activity_id = resolved_activity_id

    # 层级 / 活动 / 组织任一变更都重算归属（经 authz 统一裁决）：只显式传 org_id 时校验不够，
    # 仅改 parent_id / activity_id 也能把任务挂到其他组织或他人的 legacy 活动下。
    # 只改其他字段时整段跳过，避免重置既有 org_id。
    if {"parent_id", "activity_id", "org_id"} & provided:
        org_parent = db.get(Task, int(task.parent_id)) if task.parent_id is not None else None
        org_activity = (
            db.get(Activity, int(task.activity_id)) if task.activity_id is not None else None
        )
        # 隔离 / legacy 活动（org_id 为空）仅允许本人可见时作为挂载点，否则按不存在处理
        if (
            org_activity is not None
            and org_activity.org_id is None
            and not authz.can_view_activity(db, current_user, org_activity)
        ):
            raise ApiError(ERR_NOT_FOUND, "活动不存在")
        task.org_id = authz.resolve_task_org(
            db,
            user=current_user,
            parent=org_parent,
            activity=org_activity,
            org_id=payload.org_id if "org_id" in provided else task.org_id,
            task=task,
        )

    # title：显式提供时不允许为空
    if "title" in provided:
        title = (payload.title or "").strip()
        if not title:
            raise ApiError(ERR_INVALID_PARAM, "任务标题不能为空")
        task.title = title

    if "quota" in provided and payload.quota is not None and payload.quota < 1:
        raise ApiError(ERR_INVALID_PARAM, "需求人数必须大于 0")
    if "credit_reward" in provided and payload.credit_reward is not None and payload.credit_reward < 0:
        raise ApiError(ERR_INVALID_PARAM, "完成奖励积分不能为负数")

    # 指派对象必须存在（4040）；不能指派自己（4030）
    if "assignee_id" in provided and payload.assignee_id is not None:
        if int(payload.assignee_id) == int(current_user.id):
            raise ApiError(ERR_FORBIDDEN, "不能指派自己")
        if db.get(User, payload.assignee_id) is None:
            raise ApiError(ERR_NOT_FOUND, "指派的用户不存在")

    # 依赖集合（`C-TASK-GRAPH@1`）：显式 depends_on_ids 整体覆盖；仅 depends_on 时
    # 按单前置替换；显式空列表清空；depends_on_ids=null 视为不修改（但仍需触发归属重校验）。
    placement_changed = bool({"parent_id", "activity_id", "org_id"} & provided)
    explicit_dependency_change = (
        "depends_on" in provided
        or ("depends_on_ids" in provided and payload.depends_on_ids is not None)
    )
    if explicit_dependency_change:
        if "depends_on_ids" in provided and payload.depends_on_ids is not None:
            task_graph_service.replace_dependencies(db, task, payload.depends_on_ids)
        else:
            legacy_ids = [int(payload.depends_on)] if payload.depends_on is not None else []
            task_graph_service.replace_dependencies(db, task, legacy_ids)
    elif placement_changed:
        # 只改归属、不显式改依赖（含 depends_on_ids=null）时，旧依赖必须仍满足
        # 「同层级 / 同活动 / 同组织」；否则允许跨活动移动会留下跨范围脏边（审查 I1/第二轮）。
        existing_ids = task_graph_service.dependency_ids_bulk(db, [task]).get(int(task.id), [])
        task_graph_service.validate_dependencies(
            db,
            task_id=int(task.id),
            parent_id=task.parent_id,
            activity_id=task.activity_id,
            org_id=task.org_id,
            depends_on_ids=existing_ids,
        )

    for field in _TASK_UPDATE_FIELDS:
        if field not in provided:
            continue
        # 依赖集合已由上面的服务统一处理，避免单字段覆盖多前置
        if field == "depends_on":
            continue
        value = getattr(payload, field)
        # claim_type 为 NOT NULL 列：显式 null 视为不修改
        if field == "claim_type" and value is None:
            continue
        setattr(task, field, value)

    # extras：合并语义（键值覆盖、其它键保留）；null 视为不修改。
    # 成果提交策略（`C-SUBMISSION-POLICY@1`）在写库前校验，非法 4001 且不落库。
    if "extras" in provided and payload.extras is not None:
        incoming = normalize_acceptance(payload.extras)
        merged = {**(task.extras or {}), **incoming}
        if ACCEPTANCE_KEY in payload.extras and payload.extras[ACCEPTANCE_KEY] is None:
            merged.pop(ACCEPTANCE_KEY, None)
        task.extras = merged

    # reminder_rule：显式 null 表示清空为 null
    if "reminder_rule" in provided:
        rule = payload.reminder_rule
        task.reminder_rule = rule.model_dump() if rule is not None else None

    # status：仅允许改为 cancelled（overdue 为调度器语义，前端不主动调用）
    if "status" in provided and payload.status is not None:
        if payload.status != "cancelled":
            raise ApiError(ERR_CONFLICT, "任务当前状态不允许该操作")
        _ensure_transition(task, "cancelled")
        task.status = "cancelled"

    # 改期 / 取消后按成员状态重算聚合状态：未来截止时间可把 overdue 拉回进行中（R4）
    if "deadline" in provided or "status" in provided:
        member_service.sync_task_status(db, task)

    # 截止时间必须能解析；否则调度器会永久跳过该任务，变更通知也会失真（审查 I2）。
    if "deadline" in provided and payload.deadline is not None:
        if notify_service.deadline_version(payload.deadline) is None:
            raise ApiError(ERR_INVALID_PARAM, "截止时间格式无效")

    # 变更影响（`C-TASK-CHANGE@1`）：只对真实变化写提醒失效与通知，重复 PATCH 不重复发送。
    old_deadline_version = notify_service.deadline_version(old_deadline)
    new_deadline_version = notify_service.deadline_version(task.deadline)
    raw_deadline_changed = (
        "deadline" in provided and (task.deadline or None) != (old_deadline or None)
    )
    # 历史脏值（旧 deadline 无法解析）被清空时，两个版本都是 None，但原始值确实变化，
    # 仍需失效旧提醒并通知（审查第二轮 S3）。
    deadline_changed = "deadline" in provided and (
        old_deadline_version != new_deadline_version
        or (
            raw_deadline_changed
            and (old_deadline_version is None or new_deadline_version is None)
        )
    )
    cancelled_now = (
        "status" in provided
        and payload.status == "cancelled"
        and old_status != "cancelled"
    )
    change_payload: dict[str, Any] | None = None
    if deadline_changed or cancelled_now:
        downstream = _change_downstream_tasks(db, int(task.id), current_user)
        recipients = _change_recipients(db, task)
        if cancelled_now:
            stale_count = notify_service.stale_task_reminders(
                db, task_id=int(task.id), current_version=None
            )
            kind = "cancelled"
            notifications_created = notify_service.notify_task_changed(
                db,
                task=task,
                kind=kind,
                old_deadline=old_deadline,
                new_deadline=task.deadline,
                downstream_count=len(downstream),
                recipients=recipients,
            )
        else:
            stale_count = notify_service.stale_task_reminders(
                db,
                task_id=int(task.id),
                current_version=new_deadline_version,
            )
            kind = "deadline"
            notifications_created = notify_service.notify_task_changed(
                db,
                task=task,
                kind=kind,
                old_deadline=old_deadline,
                new_deadline=task.deadline,
                downstream_count=len(downstream),
                recipients=recipients,
            )
        change_payload = {
            "kind": kind,
            "old_deadline": old_deadline,
            "new_deadline": task.deadline,
            "reminders_stale": int(stale_count),
            "notifications_created": int(notifications_created),
            "downstream_tasks": [
                {"id": int(item.id), "title": item.title} for item in downstream
            ],
            "notified_user_ids": recipients,
        }

    db.commit()
    notify_service.publish_committed(db)
    db.refresh(task)
    data = _single_task_payload(db, task, current_user.id)
    if change_payload is not None:
        data["change"] = change_payload
    return ok(data)


# --------------------------------------------------------------------------- #
# #5 认领
# --------------------------------------------------------------------------- #
@router.post("/{task_id}/claim")
def claim_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """认领（`C-APPLY@1` A6 兼容别名）：与 ``POST /apply`` 完全等价。

    新语义下 ``claim`` 不再修改 ``assignee_id``、不再置 ``claimed``，只写入一条
    ``pending`` 报名，等待发布者审批（P1 单负责人行为已由 D1 作废）。

    实现要点：与 ``routers/applications.py::create_application`` 共用同一函数，
    延迟导入以避免 ``tasks → applications → tasks`` 的模块级循环导入。
    """
    # 延迟导入：模块级导入会构成循环（applications 顶层依赖本模块的错误码与序列化）
    from app.routers.applications import create_application

    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)
    return ok(create_application(db, task, current_user))


# --------------------------------------------------------------------------- #
# #6 指派
# --------------------------------------------------------------------------- #
@router.post("/{task_id}/assign")
def assign_task(
    task_id: int,
    payload: AssignIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """指派任务（仅发布者）：按 `C-APPLY@1` D9 语义「直接通过某成员」。

    - 有该成员的 ``pending`` 报名 ⇒ 置 ``approved``（写 ``decided_at/decided_by``）；
    - 无报名记录 ⇒ 新建一条 ``approved`` 记录（不再只覆盖 ``assignee_id``）；
    - 同样受名额约束（``4090``）；``assignee_id`` 为空时写入，``published → claimed``。
    """
    # 延迟导入：与 claim 一致，规避模块级循环导入
    from app.routers.applications import assign_approved

    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)
    authz.require_task_manage(db, current_user, task)

    target_user = db.get(User, payload.user_id)
    if target_user is None:
        raise ApiError(ERR_NOT_FOUND, "指派的用户不存在")
    if task.status not in ASSIGN_ALLOWED_STATUSES:
        raise ApiError(ERR_CONFLICT, "任务当前状态不允许该操作")

    # 状态机先校验后写库（名额与重复通过校验在 assign_approved 内完成）
    if task.status == "published":
        _ensure_transition(task, "claimed")

    task.claim_type = "assign"
    assign_approved(db, task, target_user, current_user)

    db.refresh(task)
    return ok(_single_task_payload(db, task, current_user.id))


# --------------------------------------------------------------------------- #
# #7 进度
# --------------------------------------------------------------------------- #
@router.post("/{task_id}/progress")
def add_progress(
    task_id: int,
    payload: ProgressIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """逐人提交进度记录（仅 approved 成员）：只推进本人成员状态。"""
    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)
    if not application_service.is_approved_participant(db, task, int(current_user.id)):
        raise ApiError(ERR_FORBIDDEN, "只有任务成员可以提交进度")
    if str(task.status) == "cancelled":
        raise ApiError(ERR_CONFLICT, "任务当前状态不允许该操作")

    log = ProgressLog(task_id=task.id, user_id=current_user.id, content=payload.content)
    db.add(log)
    member_service.record_progress(db, task, int(current_user.id))

    db.commit()
    db.refresh(log)

    return ok(
        ProgressOut.model_validate(
            {
                "id": log.id,
                "task_id": log.task_id,
                "user_id": log.user_id,
                "user_name": current_user.display_name,
                "content": log.content,
                "created_at": log.created_at,
            }
        ).model_dump()
    )


# --------------------------------------------------------------------------- #
# #8 提交
# --------------------------------------------------------------------------- #
@router.post("/{task_id}/submit")
def submit_task(
    task_id: int,
    payload: SubmitIn | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """成员提交完成（逐人语义）：只把**本人**成员状态置为 ``submitted``。

    可选请求体 ``{content?, resource_url?}`` 生成一条成果版本（`C-SUBMISSION@1`）；
    旧的无 body 调用仍然可用，按空内容记录版本，保持「每次提交都有版本」。
    重复提交由 ``record_submit`` 幂等处理（返回 ``changed=False``），不新增版本，
    也不重复通知发布者；通知去重键沿用 ``submit:{task_id}:{user_id}:{submitted_at}``。
    """
    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)
    if not application_service.is_approved_participant(db, task, int(current_user.id)):
        raise ApiError(ERR_FORBIDDEN, "只有任务成员可以提交完成")
    if str(task.status) == "cancelled":
        raise ApiError(ERR_CONFLICT, "任务当前状态不允许该操作")

    # 成果提交策略（`C-SUBMISSION-POLICY@1`）：先于 record_submit，失败不改成员状态、不新增版本
    submission_service.enforce_submit_policy(
        task,
        payload.content if payload is not None else None,
        payload.resource_url if payload is not None else None,
    )

    member, changed = member_service.record_submit(db, task, int(current_user.id))
    if changed:
        submission_service.create_submission(
            db,
            task,
            int(current_user.id),
            content=payload.content if payload is not None else None,
            resource_url=payload.resource_url if payload is not None else None,
        )
        notify_service.create_notification(
            db,
            user_id=int(task.publisher_id),
            task_id=int(task.id),
            level="info",
            title="有新任务待验收",
            content=f"《{task.title}》有新提交，请验收。",
            commit=False,
            dedupe_key=f"submit:{int(task.id)}:{int(current_user.id)}:{member.submitted_at}",
        )

    try:
        db.commit()
    except Exception:
        db.rollback()
        notify_service.discard_pending(db)
        raise
    notify_service.publish_committed(db)
    db.refresh(task)

    return ok(_single_task_payload(db, task, current_user.id))


@router.post("/{task_id}/submissions/upload")
def upload_submission(
    task_id: int,
    payload: SubmissionFileIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """成员上传成果文件（`C-SUBMISSION-FILE@1`），与文字提交共用逐人状态机。

    JSON + base64 传输（不引入 multipart 依赖）；格式白名单 TXT/Markdown/PDF/DOCX、
    上限 10MB；PDF/DOCX 只存储，预审不解析正文。重复提交由 ``record_submit`` 幂等处理。
    """
    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)
    if not application_service.is_approved_participant(db, task, int(current_user.id)):
        raise ApiError(ERR_FORBIDDEN, "只有任务成员可以提交完成")
    if str(task.status) == "cancelled":
        raise ApiError(ERR_CONFLICT, "任务当前状态不允许该操作")

    # 成果提交策略（`C-SUBMISSION-POLICY@1`）：通道与扩展名先校验，失败不落盘、不改成员状态
    submission_service.validate_upload_against_policy(task, payload.file_name)

    # base64 体积上限先于解码，避免超大请求进入内存解码（10MB 文件的 base64 约 13.4MB）
    if len(payload.file_base64) > 14 * 1024 * 1024:
        raise ApiError(ERR_INVALID_PARAM, "文件不能超过 10MB")
    try:
        raw = base64.b64decode(payload.file_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(ERR_INVALID_PARAM, "文件编码无效") from None
    # 先校验格式/大小，再改动成员状态；重复提交时也保持同样的错误语义。
    submission_service.validate_submission_file(payload.file_name, raw)

    member, changed = member_service.record_submit(db, task, int(current_user.id))
    if not changed:
        db.rollback()
        raise ApiError(ERR_CONFLICT, "当前成果已提交，等待验收；如需重新提交请先退回")
    if changed:
        try:
            stored = submission_service.save_submission_file(
                int(task.id), payload.file_name, raw
            )
        except ApiError:
            db.rollback()
            raise
        submission_service.create_submission(
            db,
            task,
            int(current_user.id),
            content=payload.content,
            resource_url=None,
            **stored,
        )
        notify_service.create_notification(
            db,
            user_id=int(task.publisher_id),
            task_id=int(task.id),
            level="info",
            title="有新任务待验收",
            content=f"《{task.title}》有新提交，请验收。",
            commit=False,
            dedupe_key=f"submit:{int(task.id)}:{int(current_user.id)}:{member.submitted_at}",
        )

    try:
        db.commit()
    except Exception:
        db.rollback()
        notify_service.discard_pending(db)
        if changed:
            (submission_service.SUBMISSION_UPLOAD_ROOT / str(stored["file_path"])).unlink(
                missing_ok=True
            )
        raise
    notify_service.publish_committed(db)
    db.refresh(task)

    return ok(_single_task_payload(db, task, current_user.id))


@router.get("/{task_id}/submissions/{submission_id}/file")
def download_submission_file(
    task_id: int,
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """下载成果文件：提交者本人或审核者（`require_submission_access`）。"""
    task = _get_task_or_404(db, task_id)
    submission = submission_service.get_submission(db, task, submission_id)
    submission_service.require_submission_access(db, current_user, task, submission)
    if not submission.file_path:
        raise ApiError(ERR_NOT_FOUND, "该成果没有文件")
    path = submission_service.SUBMISSION_UPLOAD_ROOT / submission.file_path
    if not path.is_file():
        raise ApiError(ERR_NOT_FOUND, "文件不存在")
    return FileResponse(
        path,
        media_type=submission.file_mime or "application/octet-stream",
        filename=submission.file_name or path.name,
    )


@router.get("/{task_id}/submissions")
def list_task_submissions(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """成果版本列表：管理者看全部成员，普通成员只看自己的版本。"""
    task = _get_task_or_404(db, task_id)
    items = submission_service.list_submissions(db, task, current_user)
    return ok({"items": [item.model_dump() for item in items]})


@router.post("/{task_id}/submissions/{submission_id}/precheck")
def precheck_submission(
    task_id: int,
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """对成果版本执行规则预审 + AI 建议；只写预审记录，不改变业务状态。"""
    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)
    result = submission_service.precheck(db, current_user, task, submission_id)
    return ok(result.model_dump())


# --------------------------------------------------------------------------- #
# #9 验收
# --------------------------------------------------------------------------- #
def _verify_targets(
    members: list[member_service.MemberView], payload: VerifyIn
) -> list[int]:
    """确定本次验收 / 退回的成员集合（`C-TASK-API@1` 目标选择规则）。"""
    if payload.user_id is not None:
        target_id = int(payload.user_id)
        if target_id not in {member.user_id for member in members}:
            raise ApiError(ERR_INVALID_PARAM, "该用户不是任务成员")
        return [target_id]

    submitted = [
        member.user_id
        for member in members
        if member.status == member_service.MEMBER_SUBMITTED
    ]
    if len(submitted) == 1:
        return submitted
    if len(submitted) > 1:
        if not payload.pass_:
            raise ApiError(ERR_INVALID_PARAM, "请指定要退回的成员")
        # 兼容旧语义：未指定成员且全部通过时，逐人全部验收
        return submitted
    raise ApiError(ERR_CONFLICT, "任务当前状态不允许该操作")


@router.post("/{task_id}/verify")
def verify_task(
    task_id: int,
    payload: VerifyIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """发布者对**单名（或多名）成员**验收：只改目标成员状态与积分。

    - ``user_id`` 指定 → 只处理该 approved 成员（非成员 4001）；
    - 未指定且恰好一名成员 ``submitted`` → 处理该成员；
    - 未指定且多名 ``submitted`` → ``pass=true`` 时逐人全部通过（兼容旧语义），
      ``pass=false`` 时返回 4001；
    - 目标成员不在 ``submitted`` → 4090；目标是发布者本人 → 4030（防御历史脏数据）；
    - ``pass=true`` 且最新成果的最新预审已过期 → 4090（要求或引用资料变化后需重新预审）；
      无预审记录视为未检查，不阻断；``pass=false`` 退回不受预审过期影响；
    - 通过：按 ``(task_id, user_id)`` 幂等加分，积分流水、成员状态与通知同一事务提交。
    """
    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)
    submission_service.require_task_review(db, current_user, task)
    if str(task.status) == "cancelled":
        raise ApiError(ERR_CONFLICT, "任务当前状态不允许该操作")

    members = member_service.effective_members(db, task)
    targets = _verify_targets(members, payload)

    # 验收绑定成果版本（`C-SUBMISSION@1`）：指定时必须等于该成员最新版本，
    # 防止页面上停留的旧稿批准新稿。校验先于任何状态写入。
    if payload.submission_id is not None:
        if len(targets) != 1:
            raise ApiError(ERR_INVALID_PARAM, "指定成果版本时只能验收一名成员")
        target = targets[0]
        submission = submission_service.get_submission(db, task, payload.submission_id)
        if int(submission.user_id) != int(target):
            raise ApiError(ERR_INVALID_PARAM, "成果版本不属于该成员")
        latest = submission_service.latest_submission(db, int(task.id), int(target))
        if latest is None or int(latest.id) != int(submission.id):
            raise ApiError(ERR_CONFLICT, "该成果版本已不是最新版本，请刷新后重新验收")

    # 防御历史库 assignee_id == publisher_id 等脏数据：绝不自我验收 / 自我加分
    if any(int(target) == int(current_user.id) for target in targets):
        raise ApiError(ERR_FORBIDDEN, "不能验收自己")

    # 先校验后写库：任一目标不在 submitted 即整体拒绝
    submitted_ids = {
        member.user_id
        for member in members
        if member.status == member_service.MEMBER_SUBMITTED
    }
    if any(target not in submitted_ids for target in targets):
        raise ApiError(ERR_CONFLICT, "任务当前状态不允许该操作")

    # 通过前校验最新预审（`C-PRECHECK-EVIDENCE@2`）：任务要求或引用资料变化后
    # 旧预审失效，即使页面未刷新也不能用过期预审批准当前成果；退回不受影响。
    if payload.pass_:
        submission_service.require_fresh_precheck(db, task, targets)

    reason = (payload.reason or "").strip() or None
    reward = (
        int(task.credit_reward)
        if task.credit_reward is not None
        else int(credit_service.DEFAULT_CREDIT_REWARD)
    )

    credited_user_ids: list[int] = []
    for target in targets:
        member = member_service.record_verification(
            db, task, target, passed=payload.pass_, reason=reason
        )
        if not payload.pass_:
            content = f"《{task.title}》验收未通过，请修改后重新提交。"
            if reason:
                content = f"{content}驳回原因：{reason}"
            notify_service.create_notification(
                db,
                user_id=int(target),
                task_id=int(task.id),
                level="warning",
                title="验收未通过",
                content=content,
                commit=False,
                dedupe_key=(
                    f"rejected:{int(task.id)}:{int(target)}:{member.submitted_at or ''}"
                ),
            )
            continue

        if not credit_service.has_task_bonus(db, int(target), int(task.id)):
            credit_service.adjust_credits(
                db,
                int(target),
                int(task.id),
                reward,
                f"{credit_service.REASON_TASK_BONUS_PREFIX}：《{task.title}》",
                commit=False,
            )
            credited_user_ids.append(int(target))
        notify_service.create_notification(
            db,
            user_id=int(target),
            task_id=int(task.id),
            level="info",
            title="验收通过，积分到账",
            content=f"《{task.title}》验收通过，获得 {reward} 积分。",
            commit=False,
            dedupe_key=f"verified:{int(task.id)}:{int(target)}",
        )

    # 全部成员验收完毕时给发布者一条汇总通知（同一去重键只保留一条）
    if payload.pass_ and str(task.status) == member_service.MEMBER_VERIFIED:
        notify_service.create_notification(
            db,
            user_id=int(current_user.id),
            task_id=int(task.id),
            level="info",
            title="验收已通过",
            content=f"《{task.title}》全部成员验收通过。",
            commit=False,
            dedupe_key=f"task_verified:{int(task.id)}",
        )

    try:
        db.commit()
    except Exception:
        db.rollback()
        notify_service.discard_pending(db)
        raise
    notify_service.publish_committed(db)

    return ok(
        VerifyOut(
            task=_single_task_payload(db, task, current_user.id),
            credit_delta=reward if payload.pass_ else 0,
            credited_user_ids=credited_user_ids,
        ).model_dump()
    )


# --------------------------------------------------------------------------- #
# #10 拆解（调用审核助手，仅返回建议，不落库）
# --------------------------------------------------------------------------- #
def _task_to_draft(task: Task) -> Draft:
    """按 `2.2.2` 关键映射表把任务字段拼成审核助手的入参草稿。"""
    return Draft(
        title=task.title,
        time=task.start_time,
        deadline=task.deadline,
        location=task.location,
        details=task.description,
        quota=task.quota,
        volunteer_hours=task.volunteer_hours,
        notes=None,
        requirements=None,
        extra_tags={str(key): str(value) for key, value in (task.extras or {}).items()},
        style_prompt=task.style_note,
    )


@router.post("/{task_id}/decompose")
def decompose_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """请求审核助手给出拆解建议（不落库，前端确认后逐个调 ``POST /api/tasks``）。"""
    task = _get_task_or_404(db, task_id)
    authz.require_task_view(db, current_user, task)
    authz.require_task_manage(db, current_user, task)

    # 延迟导入：T3 交付前本端点给出明确 5001，而不是让应用启动失败
    try:
        from app.agents import llm_client, reviewer
    except ImportError:
        logger.warning("审核助手尚未交付（T3），/decompose 暂不可用")
        raise ApiError(5001, "AI 审核服务尚未就绪")

    draft = _task_to_draft(task)
    try:
        result = reviewer.review(draft)
    except llm_client.LLMError as exc:  # 5001 / 5002 / 5003
        raise ApiError(int(getattr(exc, "code", 5001)), str(getattr(exc, "message", exc)))

    data = {
        "suggested_sub_tasks": [item.model_dump() for item in result.suggested_sub_tasks],
        # mock 标记必须与 llm_client.is_mock_mode() 同源（实现要点 7）
        "mock": bool(llm_client.is_mock_mode()),
    }
    return ok(data)


__all__ = ["router", "ALLOWED_TRANSITIONS"]