"""逐成员分级催办调度器（契约 `C-NOTIFY@1`，owner = T4）。

职责
----
1. ``start()`` / ``shutdown()``：进程内 APScheduler ``BackgroundScheduler``
   （跨线程安全）的幂等启停，由 ``main.py`` 的 lifespan 调用，本模块不改 main。
2. ``scan_and_remind(now=None)``：每轮扫描按**每个已通过成员的当前状态**生成
   ``warning`` / ``urgent`` / ``overdue`` 三级催办，并对每个未完成成员执行一次逾期扣分；
   任务没有任何 approved 成员时，回落为按截止时间给发布者的任务级提醒。
   发布者的「待验收」通知由提交路由（``submit:{task}:{user}:{submitted_at}``）负责，
   调度器不再重复发送。

硬性约束（与 design.md §2.1 / §2.3 对齐）
----------------------------------------
- 通知**只**经 ``notify_service.create_notification`` 写库（唯一入口，禁止直接 INSERT）；
- 积分**只**经 ``credit.adjust_credits`` 调整（唯一事务入口）；
- 催办对象是 ``member_service.effective_members`` 返回的已通过成员：
  ``submitted`` / ``verified`` 的成员不催办、不扣分；``rejected`` 按未完成处理；
- 催办去重键包含截止时间版本，改期后自动换新键、旧历史保留；
- 逾期扣分按 ``(task_id, user_id)`` 幂等，重复扫描、进程重启与改期都不重复扣分；
- 单任务异常隔离（try/except + rollback），脏 ``deadline`` 记 warning 后跳过；
- **禁止调用任何大模型**：文案全部由规则模板拼接，本文件不导入任何模型客户端，
  也不依赖 ``app/agents`` 下的任何模块。
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import CreditLog, Task
from app.services import credit, member_service, notify_service

logger = logging.getLogger(__name__)

#: 扫描范围：终态（verified / cancelled）不再催办；submitted / overdue 仍需催办
#: 尚未完成的成员（任务级 submitted 只表示「至少一人待验收」，见 design.md 2.3 决策 1）
SCAN_STATUSES: tuple[str, ...] = ("published", "claimed", "in_progress", "submitted", "overdue")

#: 需要催办与逾期扣分的成员状态
UNFINISHED_MEMBER_STATUSES = frozenset(
    {
        member_service.MEMBER_NOT_STARTED,
        member_service.MEMBER_IN_PROGRESS,
        member_service.MEMBER_REJECTED,
    }
)

#: ``reminder_rule`` 缺省值（null 时按该默认处理）
DEFAULT_DAYS_BEFORE = 1
DEFAULT_DAY_OF = True
DEFAULT_ON_OVERDUE = True

#: 输出格式：数据库与通知文案统一使用秒级本地时间
DEADLINE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: 入参解析格式：与 ``member_service._deadline_is_future`` 对齐；
#: 纯日期按当天 00:00 解析，ISO 形式在 :func:`_parse_deadline` 中兜底
DEADLINE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)

#: 三级催办 level 与逾期扣分常量（积分原因前缀与 ``credit`` 保持一致）
LEVEL_WARNING = "warning"
LEVEL_URGENT = "urgent"
LEVEL_OVERDUE = "overdue"
OVERDUE_PENALTY_DELTA = credit.OVERDUE_PENALTY
OVERDUE_REASON_PREFIX = credit.REASON_OVERDUE_PREFIX


JOB_ID = "reminder_scan"
DEFAULT_INTERVAL_SECONDS = 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


class ReminderRule(NamedTuple):
    """归一化后的催办规则（避免在热路径上反复处理 JSON 的脏值）。"""

    days_before: float
    day_of: bool
    on_overdue: bool


# --------------------------------------------------------------------------- #
# 启停（幂等）
# --------------------------------------------------------------------------- #
def _interval_seconds() -> int:
    """读取扫描间隔（``REMINDER_INTERVAL_SECONDS``，默认 60 秒）。"""
    raw = os.getenv("REMINDER_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("REMINDER_INTERVAL_SECONDS=%r 非法，回退默认 %s 秒", raw, DEFAULT_INTERVAL_SECONDS)
        return DEFAULT_INTERVAL_SECONDS
    if value <= 0:
        logger.warning("REMINDER_INTERVAL_SECONDS=%s 必须为正数，回退默认 %s 秒", value, DEFAULT_INTERVAL_SECONDS)
        return DEFAULT_INTERVAL_SECONDS
    return value


def start() -> None:
    """启动调度器（幂等）。``RUN_SCHEDULER=0`` 时 main.py 不会调用本函数。"""
    global _scheduler

    with _scheduler_lock:
        if _scheduler is not None:
            if _scheduler.running:
                logger.debug("reminder_scheduler.start(): 调度器已在运行，忽略重复调用")
                return
            # 已执行过 shutdown 的实例不可复用，丢弃后重建
            _scheduler = None

        interval = _interval_seconds()
        scheduler = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1})
        scheduler.add_job(
            scan_and_remind,
            trigger="interval",
            seconds=interval,
            id=JOB_ID,
            name="逐成员分级催办扫描",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.start()
        _scheduler = scheduler
        logger.info("催办调度器已启动：job=%s，间隔 %s 秒", JOB_ID, interval)


def shutdown() -> None:
    """停止调度器并等待作业结束（幂等）。"""
    global _scheduler

    with _scheduler_lock:
        scheduler = _scheduler
        _scheduler = None

    if scheduler is None:
        logger.debug("reminder_scheduler.shutdown(): 未启动，忽略")
        return

    try:
        if scheduler.running:
            scheduler.shutdown(wait=True)
        logger.info("催办调度器已停止")
    except Exception:  # 停不下来也不能阻塞进程退出
        logger.warning("催办调度器停止失败", exc_info=True)


# --------------------------------------------------------------------------- #
# 扫描主入口
# --------------------------------------------------------------------------- #
def scan_and_remind(now: datetime | None = None) -> int:
    """扫描一轮并生成催办通知，返回本次**新增通知条数**。

    ``now`` 可注入以便自动化验收（默认 ``datetime.now()``，服务器本地时间）。
    自身创建 ``SessionLocal()``，不依赖 FastAPI 的 ``Depends``；每个任务单独提交，
    单任务失败只回滚该任务。
    """
    current = now if now is not None else datetime.now()
    if current.tzinfo is not None:
        # 数据库中的 deadline 是无时区的本地时间字符串，统一成 naive 再比较
        current = current.replace(tzinfo=None)

    created = 0
    db: Session = SessionLocal()
    try:
        task_ids = list(
            db.execute(
                select(Task.id).where(Task.status.in_(SCAN_STATUSES)).order_by(Task.id)
            ).scalars()
        )
        logger.info(
            "催办扫描开始：now=%s，候选任务 %d 条",
            current.strftime(DEADLINE_FORMAT),
            len(task_ids),
        )

        for task_id in task_ids:
            try:
                task = db.get(Task, task_id)
                if task is None:  # 扫描期间被删除
                    continue
                created += _handle_task(db, task, current)
                db.commit()
                notify_service.publish_committed(db)
            except Exception:
                # 单任务失败不得中断整轮扫描
                db.rollback()
                notify_service.discard_pending(db)
                logger.warning("催办扫描：任务 %s 处理失败，已回滚并跳过", task_id, exc_info=True)

        logger.info("催办扫描结束：新增通知 %d 条", created)
    except Exception:  # 数据库整体不可用等极端情况：记录后返回，不抛出
        db.rollback()
        notify_service.discard_pending(db)
        logger.warning("催办扫描异常终止", exc_info=True)
    finally:
        db.close()

    return created


# --------------------------------------------------------------------------- #
# 单任务处理
# --------------------------------------------------------------------------- #
def _handle_task(db: Session, task: Task, now: datetime) -> int:
    """按成员状态分级处理单个任务，返回新增通知条数。"""
    # 每轮先按当前截止时间版本清理旧提醒（`C-REMINDER-STALE@1`）：
    # 改期后旧提醒立即失效；截止时间清空/无法解析时全部失效，历史记录保留。
    deadline = _parse_deadline(task.deadline)
    notify_service.stale_task_reminders(
        db,
        task_id=int(task.id),
        current_version=_deadline_version(deadline) if deadline is not None else None,
    )

    members = member_service.effective_members(db, task)
    if not members:
        # 无任何 approved 成员（含 legacy 负责人缺失）：回落为任务级发布者提醒
        return _handle_unassigned_task(db, task, now)

    created = 0
    unfinished = [member for member in members if member.status in UNFINISHED_MEMBER_STATUSES]
    if not unfinished:
        logger.info(
            "催办扫描：task_id=%s member=- level=- result=skip（成员均已提交或通过）", task.id
        )
        return created

    if deadline is None:
        logger.warning(
            "催办扫描：task_id=%s member=- level=- result=skip，"
            "deadline=%r 缺失或无法解析，不生成截止相关提醒与逾期扣分",
            task.id,
            task.deadline,
        )
        return created

    rule = _normalize_rule(task.reminder_rule)
    remaining = deadline - now
    deadline_text = _deadline_text(task, deadline)
    version = _deadline_version(deadline)

    # 1) 已逾期：逐成员催办 + 逐成员一次性扣分
    if remaining <= timedelta(0):
        if not rule.on_overdue:
            return created
        return created + _handle_overdue(db, task, unfinished, version, deadline_text)

    # 2) 24 小时内截止
    if remaining <= timedelta(hours=24):
        if not rule.day_of:
            return created
        return created + _push_member_notifications(
            db,
            task,
            unfinished,
            level=LEVEL_URGENT,
            title="任务今天截止",
            content_template="《{title}》今天 {deadline} 截止，请尽快提交。",
            deadline_text=deadline_text,
            version=version,
        )

    # 3) 提前预警窗口 (24h, days_before*24h]
    warning_window = timedelta(days=rule.days_before)
    if rule.days_before > 0 and remaining <= warning_window:
        return created + _push_member_notifications(
            db,
            task,
            unfinished,
            level=LEVEL_WARNING,
            title="任务即将截止",
            content_template="《{title}》将于 {deadline} 截止，请及时推进。",
            deadline_text=deadline_text,
            version=version,
        )

    return created


def _handle_overdue(
    db: Session, task: Task, members: list, version: str, deadline_text: str
) -> int:
    """逾期副作用：置位 ``overdue`` → 逐成员通知双方 → 逐成员一次性扣分。"""
    if task.status not in {"verified", "cancelled", "overdue"}:
        task.status = "overdue"
        db.flush()
        logger.info("催办 task_id=%s member=- level=overdue result=task_status_overdue", task.id)

    created = 0
    for member in members:
        created += _notify(
            db,
            task=task,
            user_id=member.user_id,
            level=LEVEL_OVERDUE,
            title="任务已逾期",
            content=(
                f"《{task.title}》任务已逾期：负责人 {member.user_name} 已于 {deadline_text} "
                "截止仍未提交，请尽快补交。"
            ),
            dedupe_key=f"overdue:{task.id}:{member.user_id}:{version}",
            member_name=member.user_name,
        )
        created += _notify_publisher_overdue(db, task, member, version, deadline_text)
        _apply_overdue_penalty(db, task, member)
    return created


def _notify_publisher_overdue(
    db: Session, task: Task, member: Any, version: str, deadline_text: str
) -> int:
    """逾期时通知发布者（每位成员一条，按成员去重）。"""
    if task.publisher_id == member.user_id:
        return 0
    return _notify(
        db,
        task=task,
        user_id=task.publisher_id,
        level=LEVEL_OVERDUE,
        title="任务已逾期",
        content=(
            f"《{task.title}》任务已逾期：负责人 {member.user_name} 已于 {deadline_text} "
            "截止仍未提交，请及时处理。"
        ),
        dedupe_key=f"overdue_pub:{task.id}:{task.publisher_id}:{member.user_id}:{version}",
    )


def _apply_overdue_penalty(db: Session, task: Task, member: Any) -> None:
    """逐成员逾期扣分：``(task_id, user_id)`` 幂等，改期也不重复扣分。"""
    if _has_overdue_penalty(db, task.id, member.user_id):
        logger.info(
            "催办 task_id=%s member=%s level=overdue result=penalty_skipped",
            task.id,
            member.user_name,
        )
        return

    credit.adjust_credits(
        db,
        user_id=member.user_id,
        task_id=task.id,
        delta=OVERDUE_PENALTY_DELTA,
        reason=f"{OVERDUE_REASON_PREFIX}：《{task.title}》",
        commit=False,
    )
    logger.info(
        "催办 task_id=%s member=%s level=overdue result=penalty_applied delta=%s",
        task.id,
        member.user_name,
        OVERDUE_PENALTY_DELTA,
    )


def _handle_unassigned_task(db: Session, task: Task, now: datetime) -> int:
    """无任何 approved 成员时，按截止时间为发布者生成任务级提醒（绝不写积分流水）。"""
    deadline = _parse_deadline(task.deadline)
    if deadline is None:
        logger.warning(
            "催办扫描：task_id=%s member=- level=- result=skip，"
            "deadline=%r 缺失或无法解析，不生成截止相关提醒与逾期扣分",
            task.id,
            task.deadline,
        )
        return 0

    rule = _normalize_rule(task.reminder_rule)
    remaining = deadline - now
    deadline_text = _deadline_text(task, deadline)
    version = _deadline_version(deadline)

    # 1) 已逾期：置位任务状态并通知发布者（无负责人，不扣分）
    if remaining <= timedelta(0):
        if not rule.on_overdue:
            return 0
        if task.status not in {"verified", "cancelled", "overdue"}:
            task.status = "overdue"
            db.flush()
            logger.info(
                "催办 task_id=%s member=- level=overdue result=task_status_overdue", task.id
            )
        return _notify(
            db,
            task=task,
            user_id=task.publisher_id,
            level=LEVEL_OVERDUE,
            title="任务已逾期",
            content=f"《{task.title}》任务已逾期：已于 {deadline_text} 截止且暂无负责人，请及时处理。",
            dedupe_key=f"unassigned:{task.id}:{task.publisher_id}:{LEVEL_OVERDUE}:{version}",
            member_name="-",
        )

    # 2) 24 小时内截止
    if remaining <= timedelta(hours=24):
        if not rule.day_of:
            return 0
        level = LEVEL_URGENT
        title = "任务今天截止"
        content = (
            f"《{task.title}》今天 {deadline_text} 截止，任务暂无负责人，请及时处理或指派成员。"
        )
    # 3) 提前预警窗口 (24h, days_before*24h]
    elif rule.days_before > 0 and remaining <= timedelta(days=rule.days_before):
        level = LEVEL_WARNING
        title = "任务即将截止"
        content = (
            f"《{task.title}》将于 {deadline_text} 截止，任务暂无负责人，请及时处理或指派成员。"
        )
    else:
        return 0

    return _notify(
        db,
        task=task,
        user_id=task.publisher_id,
        level=level,
        title=title,
        content=content,
        dedupe_key=f"unassigned:{task.id}:{task.publisher_id}:{level}:{version}",
        member_name="-",
    )


def _push_member_notifications(
    db: Session,
    task: Task,
    members: list,
    *,
    level: str,
    title: str,
    content_template: str,
    deadline_text: str,
    version: str,
) -> int:
    """对每个未完成成员写入一条分级催办（按 ``(task, member, level, deadline)`` 去重）。"""
    created = 0
    for member in members:
        created += _notify(
            db,
            task=task,
            user_id=member.user_id,
            level=level,
            title=title,
            content=content_template.format(title=task.title, deadline=deadline_text),
            dedupe_key=f"remind:{task.id}:{member.user_id}:{level}:{version}",
            member_name=member.user_name,
        )
    return created


# --------------------------------------------------------------------------- #
# 查询与写库（唯一入口）
# --------------------------------------------------------------------------- #
def _notify(
    db: Session,
    *,
    task: Task,
    user_id: int,
    level: str,
    title: str,
    content: str,
    dedupe_key: str,
    member_name: str | None = None,
) -> int:
    """按去重键写入一条通知，返回新增条数（0/1），并记录 task/member/level/result 日志。"""
    member_label = member_name if member_name is not None else user_id
    if notify_service.notification_exists(
        db, user_id=user_id, task_id=task.id, dedupe_key=dedupe_key
    ):
        logger.info(
            "催办 task_id=%s member=%s level=%s result=dedupe", task.id, member_label, level
        )
        return 0

    notify_service.create_notification(
        db,
        user_id=user_id,
        task_id=task.id,
        level=level,
        title=title,
        content=content,
        commit=False,
        dedupe_key=dedupe_key,
    )
    logger.info(
        "催办 task_id=%s member=%s level=%s result=created", task.id, member_label, level
    )
    return 1


def _has_overdue_penalty(db: Session, task_id: int, user_id: int) -> bool:
    """该任务该成员是否已有「逾期扣分」流水（``(task_id, user_id)`` 幂等）。"""
    stmt = (
        select(CreditLog.id)
        .where(
            CreditLog.task_id == task_id,
            CreditLog.user_id == user_id,
            CreditLog.reason.like(f"{OVERDUE_REASON_PREFIX}%"),
        )
        .limit(1)
    )
    return db.execute(stmt).first() is not None


# --------------------------------------------------------------------------- #
# 纯函数工具
# --------------------------------------------------------------------------- #
def _parse_deadline(value: Any) -> datetime | None:
    """把 ``tasks.deadline`` 字符串解析为 naive datetime；失败返回 None。

    解析口径与 ``member_service._deadline_is_future`` 一致：接受
    ``YYYY-MM-DD HH:MM:SS``、``YYYY-MM-DD HH:MM``、``YYYY-MM-DD``（按当天 00:00）
    以及 ISO 形式（``2026-11-11T10:00:00``），其余一律视为非法并跳过。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    parsers = [lambda s, fmt=fmt: datetime.strptime(s, fmt) for fmt in DEADLINE_FORMATS]
    parsers.append(datetime.fromisoformat)

    for parser in parsers:
        try:
            parsed = parser(text)
        except (ValueError, TypeError):
            continue
        if parsed.tzinfo is not None:
            # 带时区输入按系统本地时区换算后再去掉 tzinfo（与 member_service 一致）
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    return None


def _deadline_text(task: Task, deadline: datetime) -> str:
    """通知文案中的截止时间：优先回显库里的原始字符串。"""
    raw = task.deadline
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return deadline.strftime(DEADLINE_FORMAT)


def _deadline_version(deadline: datetime) -> str:
    """截止时间版本（去重键的一部分）：改期后键变化，旧通知历史保留。"""
    return deadline.strftime(DEADLINE_FORMAT)


def _as_bool(value: Any, default: bool) -> bool:
    """宽松布尔归一化（``reminder_rule`` 由前端 JSON 提供，可能存在脏值）。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _as_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result >= 0 else 0.0


def _normalize_rule(raw: Any) -> ReminderRule:
    """把 ``tasks.reminder_rule``（JSON/None）归一化为 ``ReminderRule``。"""
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("reminder_rule=%r 不是对象，使用默认规则", raw)
        return ReminderRule(
            days_before=float(DEFAULT_DAYS_BEFORE),
            day_of=DEFAULT_DAY_OF,
            on_overdue=DEFAULT_ON_OVERDUE,
        )

    return ReminderRule(
        days_before=_as_float(raw.get("days_before", DEFAULT_DAYS_BEFORE), float(DEFAULT_DAYS_BEFORE)),
        day_of=_as_bool(raw.get("day_of"), DEFAULT_DAY_OF),
        on_overdue=_as_bool(raw.get("on_overdue"), DEFAULT_ON_OVERDUE),
    )