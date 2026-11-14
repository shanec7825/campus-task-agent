"""AI 任务查询增强（契约 `C-AI-TASK-QUERY@1`）。

* 先在当前用户可见任务里按问题关键词与意图打分，再按相关度降序返回；
* 没有任何关键词 / 意图命中时退化为按截止时间排列的最近可见任务，
  保持旧 ``ai_service._visible_context`` 的行为；
* 成果与成员信息只对最终入选的一小批任务批量查询：审阅者（与
  ``submission_service.can_review_task`` 同口径）取该任务全部成员的最新版本与
  验收结果，其他人只取本人最新提交，``review_result`` 只依据任务聚合状态，
  不把他人成果内容、链接、文件名或退回原因送入模型；
* 可见性完全复用 :mod:`app.services.authz`，不新增权限模型；
* 只读：不写任何表，不以 ORM 对象逃逸出调用边界。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.models import Activity, Task, TaskMember, TaskSubmission, User
from app.schemas import ACCEPTANCE_KEY
from app.services import authz, kb_service
from app.services.submission_service import can_review_task

DEFAULT_LIMIT = 12
MAX_LIMIT = 50
#: 打分候选上限：只为最近的一批可见任务打分，避免全表扫描与无界分词。
MAX_CANDIDATES = 200
#: 单字段截断：防止 SOP / 成果挤占模型上下文。
FIELD_LIMIT = 200
#: 任务描述沿用旧 ``_visible_context`` 的 300 字符口径。
DESCRIPTION_LIMIT = 300
#: 分词输入上限：问题与任务要求都先切片，避免超长文本触发无界分词。
MAX_QUERY_CHARS = 500
MAX_ANALYZE_CHARS = 2000

KEYWORD_WEIGHT = 2
STATE_WEIGHT = 1
OVERDUE_WEIGHT = 2
SCOPE_WEIGHT = 1

OVERDUE_WORDS = ("逾期", "过期", "超期", "迟交", "deadline")
REVIEW_WORDS = ("待验收", "待审核", "审核", "验收")
MINE_WORDS = ("待办", "我的任务", "我负责", "我参与")

#: 已收尾的任务状态：不再计入「逾期」。
FINISHED_TASK_STATUSES = frozenset({"verified", "cancelled"})

_DEADLINE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def _parse_deadline(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in _DEADLINE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _is_overdue(task: Task, now: datetime) -> bool:
    if task.status in FINISHED_TASK_STATUSES:
        return False
    deadline = _parse_deadline(task.deadline)
    return deadline is not None and deadline < now


def _clip(value: str | None, limit: int = FIELD_LIMIT) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _requirement_text(task: Task) -> str:
    """SOP 与描述合并后截断到 ``MAX_ANALYZE_CHARS``，作为关键词打分文本。"""
    merged = f"{task.sop_guide or ''} {task.description or ''}".strip()
    return merged[:MAX_ANALYZE_CHARS]


def _acceptance_text(task: Task) -> str | None:
    """把 ``extras["acceptance"]`` 的提交策略文本化，作为验收要求的一部分。"""
    extras = task.extras if isinstance(task.extras, dict) else {}
    raw = extras.get(ACCEPTANCE_KEY)
    if not isinstance(raw, dict):
        return None
    parts: list[str] = []
    modes = [str(item) for item in (raw.get("modes") or []) if str(item).strip()]
    if modes:
        parts.append("提交方式：" + "/".join(modes))
    exts = [str(item) for item in (raw.get("allowed_exts") or []) if str(item).strip()]
    if exts:
        parts.append("文件类型：" + "/".join(exts))
    if raw.get("ai_precheck"):
        parts.append("提交后需 AI 预审")
    return "；".join(parts) or None


def _submission_text(submission: TaskSubmission | None) -> str | None:
    if submission is None:
        return None
    parts = [f"v{submission.version}"]
    if submission.content:
        parts.append(str(submission.content).strip()[:80])
    if submission.resource_url:
        parts.append(str(submission.resource_url))
    if submission.file_name:
        parts.append(f"文件 {submission.file_name}")
    return " · ".join(parts)


def _review_result(task: Task, member: TaskMember | None, can_review: bool) -> str | None:
    """审阅者可用提交人成员行；其他人只依据任务聚合状态，不暴露他人退回原因。"""
    if can_review and member is not None:
        if member.status == "verified":
            suffix = f"（{member.verified_at}）" if member.verified_at else ""
            return _clip(f"已验收{suffix}")
        if member.status == "rejected":
            reason = (member.rejection_reason or "").strip()
            return _clip(f"验收未通过：{reason}" if reason else "验收未通过")
        if member.status == "submitted":
            return "待验收"
    if task.status == "verified":
        return "已验收"
    if task.status == "submitted":
        return "待验收"
    return None


def _intents(question: str) -> dict[str, bool]:
    text = question or ""
    return {
        "overdue": any(word in text for word in OVERDUE_WORDS),
        "review": any(word in text for word in REVIEW_WORDS),
        "mine": any(word in text for word in MINE_WORDS),
    }


def _awaiting_review_task_ids(db: Session, task_ids: list[int]) -> set[int]:
    """一次批量查询「有成员已提交待验收」的任务 ID，避免逐任务查询。"""
    if not task_ids:
        return set()
    rows = db.execute(
        select(TaskMember.task_id)
        .where(TaskMember.task_id.in_(task_ids), TaskMember.status == "submitted")
        .distinct()
    ).scalars()
    return {int(task_id) for task_id in rows}


def _latest_submissions(
    db: Session,
    task_ids: list[int],
    viewer_id: int,
    reviewable_ids: set[int],
) -> dict[int, TaskSubmission]:
    """一次批量查询最新成果；非审阅者只保留本人版本（与 TaskDetail 可见性一致）。"""
    if not task_ids:
        return {}
    rows = db.execute(
        select(TaskSubmission)
        .where(TaskSubmission.task_id.in_(task_ids))
        .order_by(
            TaskSubmission.task_id.asc(),
            TaskSubmission.version.desc(),
            TaskSubmission.id.desc(),
        )
    ).scalars()
    latest: dict[int, TaskSubmission] = {}
    for row in rows:
        task_id = int(row.task_id)
        if task_id not in reviewable_ids and int(row.user_id) != int(viewer_id):
            continue
        latest.setdefault(task_id, row)
    return latest


def _members_by_task(db: Session, task_ids: list[int]) -> dict[int, dict[int, TaskMember]]:
    """一次批量查询成员执行行（只对审阅者可审阅的任务调用）。"""
    if not task_ids:
        return {}
    rows = db.execute(
        select(TaskMember).where(TaskMember.task_id.in_(task_ids))
    ).scalars()
    grouped: dict[int, dict[int, TaskMember]] = {}
    for row in rows:
        grouped.setdefault(int(row.task_id), {})[int(row.user_id)] = row
    return grouped


def _rank_key(entry: tuple[int, Task, Activity | None]):
    score, task, _activity = entry
    deadline = _parse_deadline(task.deadline)
    return (
        -score,
        0 if deadline is not None else 1,
        deadline or datetime.max,
        int(task.id),
    )


def _to_dict(
    score: int,
    task: Task,
    activity: Activity | None,
    submission: TaskSubmission | None,
    member: TaskMember | None,
    can_review: bool,
) -> dict[str, object]:
    return {
        "task_id": int(task.id),
        "title": task.title,
        "activity_name": activity.title if activity is not None else None,
        "status": task.status,
        "deadline": task.deadline,
        "location": task.location,
        "sop": _clip(task.sop_guide),
        "acceptance": _clip(_acceptance_text(task)),
        "latest_submission": _clip(_submission_text(submission)),
        "review_result": _review_result(task, member, can_review),
        "score": int(score),
        # 追加字段（不属于契约列表）：ai_service 仍需活动 ID 生成引用、描述保持旧上下文。
        "activity_id": int(activity.id) if activity is not None else None,
        "description": _clip(task.description, DESCRIPTION_LIMIT),
    }


def _score_entries(
    db: Session,
    question: str,
    rows: list,
    intents: dict[str, bool],
    scoped: bool,
) -> tuple[list[tuple[int, Task, Activity | None]], bool]:
    """对候选任务打分，返回 ``(entries, matched)``。

    问题没有可用关键词时不做逐任务分词（只保留意图加分），避免 200 条候选的
    无谓分词；SOP 与描述在分词前已截断到 ``MAX_ANALYZE_CHARS``。
    """
    q_tokens = set(kb_service.tokenize((question or "")[:MAX_QUERY_CHARS]))
    awaiting_ids: set[int] = set()
    if intents["review"]:
        awaiting_ids = _awaiting_review_task_ids(
            db, [int(task.id) for task, _activity, _is_mine in rows]
        )

    now = datetime.now()
    entries: list[tuple[int, Task, Activity | None]] = []
    matched = False
    for task, activity, is_mine in rows:
        task_id = int(task.id)
        keyword_hits = 0
        if q_tokens:
            keyword_hits = len(
                q_tokens & set(kb_service.tokenize((task.title or "")[:MAX_ANALYZE_CHARS]))
            )
            keyword_hits += len(q_tokens & set(kb_service.tokenize(_requirement_text(task))))
            if activity is not None:
                keyword_hits += len(
                    q_tokens
                    & set(kb_service.tokenize((activity.title or "")[:MAX_ANALYZE_CHARS]))
                )

        score = KEYWORD_WEIGHT * keyword_hits
        if keyword_hits:
            matched = True
        if intents["overdue"] and _is_overdue(task, now):
            score += OVERDUE_WEIGHT
            matched = True
        if intents["review"] and (task.status == "submitted" or task_id in awaiting_ids):
            score += STATE_WEIGHT
            matched = True
        if intents["mine"] and bool(is_mine):
            score += STATE_WEIGHT
            matched = True
        if scoped:
            score += SCOPE_WEIGHT
        entries.append((score, task, activity))
    return entries, matched


def build_task_context(
    db: Session,
    user: User,
    question: str,
    scope_type: str = "general",
    scope_id: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """按问题相关度返回可见任务上下文，字段与排序见 `C-AI-TASK-QUERY@1`。

    打分：标题 / SOP+描述 / 活动名关键词每命中一个 token ``+2``；逾期意图命中逾期
    任务 ``+2``；待验收意图命中待验收任务 ``+1``；待办意图命中「我的任务」``+1``；
    活动 / 任务作用域内任务 ``+1``。没有任何命中时按截止时间升序（NULL 最后）
    返回最近任务，与旧上下文行为一致。
    """
    bounded = max(1, min(int(limit), MAX_LIMIT))
    normalized_scope = scope_type or "general"
    scoped = normalized_scope in ("activity", "task")

    query = (
        select(Task, Activity, authz.my_task_condition(db, user).label("is_mine"))
        .outerjoin(Activity, Activity.id == Task.activity_id)
        .where(authz.visible_task_filter(db, user))
    )
    if normalized_scope == "activity":
        if scope_id is None:
            return []
        query = query.where(Task.activity_id == int(scope_id))
    elif normalized_scope == "task":
        if scope_id is None:
            return []
        task = db.get(Task, int(scope_id))
        activity_id = (
            int(task.activity_id)
            if task is not None and task.activity_id is not None
            else None
        )
        if activity_id is None:
            query = query.where(Task.id == int(scope_id))
        else:
            query = query.where(
                or_(Task.id == int(scope_id), Task.activity_id == activity_id)
            )

    rows = db.execute(
        query.order_by(
            case((Task.deadline.is_(None), 1), else_=0),
            Task.deadline.asc(),
            Task.id.asc(),
        ).limit(MAX_CANDIDATES)
    ).all()
    if not rows:
        return []

    q_tokens = kb_service.tokenize((question or "")[:MAX_QUERY_CHARS])
    intents = _intents(question)
    if not q_tokens and not any(intents.values()):
        # 没有可用关键词也没有意图：不做分词，直接按截止时间取最近任务。
        selected: list[tuple[int, Task, Activity | None]] = [
            (0, task, activity) for task, activity, _is_mine in rows[:bounded]
        ]
    else:
        entries, matched = _score_entries(db, question, rows, intents, scoped)
        if matched:
            entries.sort(key=_rank_key)
        selected = entries[:bounded]

    selected_ids = [int(task.id) for _score, task, _activity in selected]
    reviewable = {
        int(task.id)
        for _score, task, _activity in selected
        if can_review_task(db, user, task)
    }
    submissions = _latest_submissions(db, selected_ids, int(user.id), reviewable)
    member_task_ids = [task_id for task_id in selected_ids if task_id in reviewable]
    members = _members_by_task(db, member_task_ids)

    results: list[dict[str, object]] = []
    for score, task, activity in selected:
        task_id = int(task.id)
        submission = submissions.get(task_id)
        can_review = task_id in reviewable
        member = (
            members.get(task_id, {}).get(int(submission.user_id))
            if can_review and submission is not None
            else None
        )
        results.append(_to_dict(score, task, activity, submission, member, can_review))
    return results


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_ANALYZE_CHARS",
    "MAX_CANDIDATES",
    "MAX_LIMIT",
    "MAX_QUERY_CHARS",
    "build_task_context",
]