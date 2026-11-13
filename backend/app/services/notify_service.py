"""通知落库 + 推送（契约 `C-NOTIFY@1`，owner = T4 去重面）。

本模块是**唯一**写入 ``notifications`` 表的入口（见计划 `2.3` 服务交互矩阵）：

1. ``db.add`` + ``db.commit`` + ``db.refresh``；
2. 调用 ``notification_hub.publish(user_id, payload)``；
3. 返回 ORM 对象。调用方不再对该记录做 commit。

``commit=False`` 是向后兼容的扩展参数：供「任务状态 + 积分流水 + 通知」需要在
**同一事务**内落库的场景（``POST /api/tasks/{id}/verify``、催办调度器的一轮扫描）
使用 —— 此时本函数只 ``flush`` 分配主键、把待推送记录登记在 ``db.info`` 上，等调用方
完成统一 ``commit`` 后再调用 :func:`publish_committed` 统一推送。

``dedupe_key`` 提供通知幂等：同一接收人、同一任务、同一 key 只落一条；重复调用返回
已有记录且不写库、不推送。并发插入撞上唯一索引 ``uq_notifications_dedupe_key`` 时，
回滚到本次插入前的 savepoint 并返回已存在记录，历史通知永不删除。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app.models import Notification
from app.schemas import NotificationOut
from app.services import notification_hub

logger = logging.getLogger(__name__)

# 挂在 Session.info 上的待推送登记键（同一事务内的多条通知）
_PENDING_KEY = "cta_pending_notifications"

#: 提醒类通知的 dedupe_key 前缀（`C-REMINDER-STALE@1`）：只有这些记录会被改期/取消失效。
REMINDER_DEDUPE_PREFIXES: tuple[str, ...] = (
    "remind:",
    "overdue:",
    "overdue_pub:",
    "unassigned:",
)

#: 截止时间入库格式；与 reminder_scheduler 的解析口径保持一致。
DEADLINE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def _publish(notification: Notification) -> None:
    """把数据库记录转换为 ``NotificationOut`` 字典并推送（内部实现）。"""
    try:
        payload: dict[str, Any] = NotificationOut.model_validate(notification).model_dump()
    except Exception:  # 序列化失败不得影响已提交的业务事务
        logger.warning("通知序列化失败，跳过推送 id=%s", getattr(notification, "id", None), exc_info=True)
        return
    notification_hub.publish(int(notification.user_id), payload)


def _find_by_dedupe_key(
    db: Session, *, user_id: int, task_id: int | None, dedupe_key: str
) -> Notification | None:
    """在 ``(user_id, task_id, dedupe_key)`` 上查找已有通知。"""
    stmt = select(Notification).where(
        Notification.user_id == int(user_id),
        Notification.dedupe_key == dedupe_key,
    )
    if task_id is None:
        stmt = stmt.where(Notification.task_id.is_(None))
    else:
        stmt = stmt.where(Notification.task_id == int(task_id))
    return db.execute(stmt.limit(1)).scalars().first()


def notification_exists(
    db: Session, *, user_id: int, task_id: int | None, dedupe_key: str
) -> bool:
    """判断同一接收人、同一任务是否已存在该 ``dedupe_key`` 的通知。"""
    return _find_by_dedupe_key(db, user_id=user_id, task_id=task_id, dedupe_key=dedupe_key) is not None


def _discard(db: Session, notification: Notification) -> None:
    """savepoint 回滚后把本次待插入的对象移出会话，避免下次 flush 再次写入。"""
    if object_session(notification) is db:
        try:
            db.expunge(notification)
        except Exception:  # 对象已被回滚出去时无需处理
            logger.debug("通知对象已不在会话中，忽略 expunge 失败", exc_info=True)


def create_notification(
    db: Session,
    *,
    user_id: int,
    task_id: int | None,
    level: str,
    title: str,
    content: str,
    commit: bool = True,
    dedupe_key: str | None = None,
) -> Notification:
    """写入一条通知并（可选）立即推送。

    Args:
        db: 当前请求 / 调度轮次的 SQLAlchemy 会话。
        user_id: 接收人。
        task_id: 关联任务（可为空）。
        level: ``info|warning|urgent|overdue``；本函数不做枚举校验（避免调度器中断）。
        title: 通知标题。
        content: 通知正文。
        commit: 为 ``True``（默认）时立即提交并推送；为 ``False`` 时仅 ``flush``，
            由调用方在统一 ``commit`` 之后调用 :func:`publish_committed`。
        dedupe_key: 幂等键；``None`` 表示不做去重。同一接收人、同一任务重复的 key
            直接返回已有记录，不写库也不推送。

    Returns:
        已落库（或已 flush 出主键 / 命中去重的已有）ORM 对象。
    """
    if dedupe_key is not None:
        existing = _find_by_dedupe_key(
            db, user_id=user_id, task_id=task_id, dedupe_key=dedupe_key
        )
        if existing is not None:
            logger.debug(
                "通知去重命中：user_id=%s task_id=%s dedupe_key=%s", user_id, task_id, dedupe_key
            )
            return existing

    notification = Notification(
        user_id=user_id,
        task_id=task_id,
        level=level,
        title=title,
        content=content,
    )
    if dedupe_key is not None:
        notification.dedupe_key = dedupe_key
    db.add(notification)

    if dedupe_key is not None:
        # 唯一索引可能被并发写入撞上：只回滚本次插入的 savepoint
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            _discard(db, notification)
            existing = _find_by_dedupe_key(
                db, user_id=user_id, task_id=task_id, dedupe_key=dedupe_key
            )
            if existing is None:
                raise
            logger.debug(
                "通知并发去重命中：user_id=%s task_id=%s dedupe_key=%s",
                user_id,
                task_id,
                dedupe_key,
            )
            return existing

    if commit:
        db.commit()
        db.refresh(notification)
        _publish(notification)
        return notification

    db.flush()
    pending = db.info.setdefault(_PENDING_KEY, [])
    pending.append(notification)
    return notification


def publish_committed(db: Session) -> None:
    """在调用方完成统一 ``commit`` 之后，推送本事务内登记的全部通知。"""
    pending: list[Notification] = db.info.pop(_PENDING_KEY, [])
    for notification in pending:
        # rollback 之后主键会变回 None，跳过这类未真正落库的记录
        if getattr(notification, "id", None) is None:
            continue
        _publish(notification)


# --------------------------------------------------------------------------- #
# 报名 / 审批文案（契约 `C-APPLY@1` 通知文案表，owner = T2）
# --------------------------------------------------------------------------- #
#: key → (level, title, content_template)；``content_template`` 只做 ``str.format``，
#: 不涉及 Prompt（禁止对 Prompt 正文做格式化）。
APPLY_NOTICE_TEMPLATES: dict[str, tuple[str, str, str]] = {
    # key: (level, title, content_template)
    "applied_to_publisher": ("info", "新的报名申请", "{user} 申请参加《{title}》，请及时审批。"),
    "applied_to_student": ("info", "报名已提交", "你已报名《{title}》，等待发布者确认。"),
    "withdraw_to_publisher": ("info", "报名已撤回", "{user} 撤回了《{title}》的报名。"),
    "approved_to_student": ("info", "报名已通过", "你报名《{title}》已通过，可以开始推进。"),
    "rejected_to_student": ("warning", "报名未通过", "你报名《{title}》未通过。原因：{reason}"),
}


def apply_notice(
    db: Session,
    *,
    key: str,
    user_id: int,
    task_id: int,
    commit: bool = True,
    **fields: str,
) -> Notification:
    """按模板构造并写入一条报名/审批通知。

    Args:
        db: 请求级会话。
        key: :data:`APPLY_NOTICE_TEMPLATES` 的键。
        user_id: 接收人。
        task_id: 关联任务。
        commit: ``True`` 时立即提交并推送；``False`` 时仅 ``flush``，
            由调用方统一 ``commit`` 后调用 :func:`publish_committed`。
        **fields: 模板占位符取值（``user`` / ``title`` / ``reason``）。

    Returns:
        已落库（或已 flush 出主键）的 ORM 对象。

    Raises:
        KeyError: ``key`` 不在模板表中。
    """
    level, title, content_template = APPLY_NOTICE_TEMPLATES[key]
    return create_notification(
        db,
        user_id=int(user_id),
        task_id=int(task_id),
        level=level,
        title=title,
        content=content_template.format(**fields),
        commit=commit,
    )


def notify_applied(
    db: Session,
    *,
    publisher_id: int,
    student_id: int,
    student_name: str,
    task_id: int,
    title: str,
    commit: bool = False,
) -> None:
    """学生报名成功：同时通知发布者与报名学生（两条通知，同一事务）。"""
    apply_notice(
        db,
        key="applied_to_publisher",
        user_id=publisher_id,
        task_id=task_id,
        commit=commit,
        user=student_name,
        title=title,
    )
    apply_notice(
        db,
        key="applied_to_student",
        user_id=student_id,
        task_id=task_id,
        commit=commit,
        title=title,
    )


def notify_withdrawn(
    db: Session,
    *,
    publisher_id: int,
    student_name: str,
    task_id: int,
    title: str,
    commit: bool = False,
) -> None:
    """学生撤回报名：通知发布者。"""
    apply_notice(
        db,
        key="withdraw_to_publisher",
        user_id=publisher_id,
        task_id=task_id,
        commit=commit,
        user=student_name,
        title=title,
    )


def notify_decided(
    db: Session,
    *,
    student_id: int,
    task_id: int,
    title: str,
    approved: bool,
    reason: str | None = None,
    commit: bool = False,
) -> None:
    """审批结果通知学生：通过 → ``info``；拒绝 → ``warning``（含原因）。"""
    if approved:
        apply_notice(
            db,
            key="approved_to_student",
            user_id=student_id,
            task_id=task_id,
            commit=commit,
            title=title,
        )
        return
    apply_notice(
        db,
        key="rejected_to_student",
        user_id=student_id,
        task_id=task_id,
        commit=commit,
        title=title,
        reason=reason or "",
    )


def discard_pending(db: Session) -> None:
    """事务回滚时丢弃待推送登记，避免推送未落库的数据。"""
    db.info.pop(_PENDING_KEY, None)


# --------------------------------------------------------------------------- #
# 旧提醒失效与变更通知（契约 `C-REMINDER-STALE@1` / `C-TASK-CHANGE@1`）
# --------------------------------------------------------------------------- #
def deadline_version(value: str | None) -> str | None:
    """把截止时间字符串归一化为去重键版本；无法解析返回 ``None``。

    与 ``reminder_scheduler._parse_deadline`` 使用同一组格式；带时区输入按系统本地
    时区换算后去掉 tzinfo，保证改期前后比较的是同一时间口径。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    parsers = [lambda s, fmt=fmt: datetime.strptime(s, fmt) for fmt in DEADLINE_FORMATS]
    parsers.append(datetime.fromisoformat)
    for parser in parsers:
        try:
            parsed = parser(text)
        except (ValueError, TypeError):
            continue
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return None


def stale_task_reminders(
    db: Session,
    *,
    task_id: int,
    current_version: str | None,
    commit: bool = False,
) -> int:
    """把同一任务中不属于当前截止时间版本的提醒标记为失效。

    ``current_version`` 为空表示截止时间已清空/任务取消，全部提醒失效；非空时只保留
    dedupe_key 末尾等于当前版本的提醒。返回本次新失效的条数。历史记录不删除。
    """
    filters = [
        Notification.task_id == int(task_id),
        Notification.stale == 0,
        Notification.dedupe_key.isnot(None),
        or_(*[Notification.dedupe_key.like(f"{prefix}%") for prefix in REMINDER_DEDUPE_PREFIXES]),
    ]
    rows = db.execute(select(Notification).where(*filters)).scalars().all()
    changed = 0
    for notification in rows:
        key = notification.dedupe_key or ""
        if current_version is not None and key.endswith(f":{current_version}"):
            continue
        notification.stale = 1
        changed += 1
    if changed:
        db.flush()
        logger.info("旧提醒失效 task_id=%s count=%s current_version=%s", task_id, changed, current_version)
    if commit:
        db.commit()
    return changed


def notify_task_changed(
    db: Session,
    *,
    task,
    kind: str,
    old_deadline: str | None,
    new_deadline: str | None,
    downstream_count: int,
    recipients: list[int],
    commit: bool = False,
) -> int:
    """写改期/取消变更通知（同一接收人去重），返回新增条数。

    ``kind`` 为 ``deadline`` 或 ``cancelled``；通知去重键包含任务与新旧值，
    同一变更重试不会重复发送。``recipients`` 由调用方按任务可见成员计算。
    """
    if kind == "cancelled":
        title = "任务已取消"
        content = (
            f"《{task.title}》已取消，后续不再提醒与验收。"
            + (f"受影响后续任务 {downstream_count} 个。" if downstream_count else "")
        )
        dedupe_key = f"change:cancelled:{task.id}"
    else:
        old_text = old_deadline or "未设置"
        new_text = new_deadline or "未设置"
        title = "任务截止时间已调整"
        content = (
            f"《{task.title}》截止时间由 {old_text} 调整为 {new_text}；"
            "后续提醒将按新时间重新计算。"
            + (f"受影响后续任务 {downstream_count} 个。" if downstream_count else "")
        )
        dedupe_key = f"change:deadline:{task.id}:{old_text}:{new_text}"

    created = 0
    seen: set[int] = set()
    for user_id in recipients:
        uid = int(user_id)
        if uid in seen:
            continue
        seen.add(uid)
        # 通知唯一索引只建在 dedupe_key 上（既有契约），因此接收人必须进入 key，
        # 否则同一变更给发布者和成员写两条会撞 UNIQUE。
        user_key = f"{dedupe_key}:{uid}"
        if notification_exists(db, user_id=uid, task_id=int(task.id), dedupe_key=user_key):
            logger.debug("变更通知去重命中 task_id=%s user_id=%s key=%s", task.id, uid, user_key)
            continue
        create_notification(
            db,
            user_id=uid,
            task_id=int(task.id),
            level="info",
            title=title,
            content=content,
            commit=False,
            dedupe_key=user_key,
        )
        created += 1
    if commit and created:
        db.commit()
        publish_committed(db)
    return created


__all__ = [
    "create_notification",
    "notification_exists",
    "publish_committed",
    "discard_pending",
    "deadline_version",
    "stale_task_reminders",
    "notify_task_changed",
    "REMINDER_DEDUPE_PREFIXES",
    "APPLY_NOTICE_TEMPLATES",
    "apply_notice",
    "notify_applied",
    "notify_withdrawn",
    "notify_decided",
]