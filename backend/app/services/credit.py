"""积分事务（契约 `2.3.1` 共享行为表，owner = T2）。

唯一实现位置：写 ``credit_logs`` + ``users.credits += delta``，两者在同一事务内提交，
保证「余额 == 流水之和」（R6-AC1 / R6-AC5）。

调用方：
- 验收通过加分（T2：``POST /api/tasks/{id}/verify``）；
- 逾期一次性扣分（T4：``reminder_scheduler.scan_and_remind``）。

``commit=False`` 是向后兼容的扩展参数：验收接口需要把「任务状态 + 积分流水 +
用户余额 + 通知」放在同一个 ``commit`` 内，因此先 ``flush``，由调用方统一提交。
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import CreditLog, User

logger = logging.getLogger(__name__)

# 积分流水原因前缀（幂等判定的唯一口径，见计划 `2.3.1` 积分规则表）
REASON_TASK_BONUS_PREFIX = "任务完成奖励"
REASON_OVERDUE_PREFIX = "逾期扣分"

# 验收通过且任务未设置 credit_reward 时的默认加分（R6-AC2）
DEFAULT_CREDIT_REWARD = 20

# 逾期一次性扣分（R6-AC3）
OVERDUE_PENALTY = -10


def adjust_credits(
    db: Session,
    user_id: int,
    task_id: int | None,
    delta: int,
    reason: str,
    *,
    commit: bool = True,
) -> int:
    """调整用户积分并写流水，返回调整后的余额。

    Args:
        db: SQLAlchemy 会话。
        user_id: 被调整的用户。
        task_id: 关联任务（可为空）。
        delta: 变化量（可为负，R6-AC4 不设下限）。
        reason: 流水原因（幂等判定依赖前缀，见模块常量）。
        commit: ``True``（默认）时立即提交；``False`` 时仅 ``flush``。

    Returns:
        调整后的用户积分余额。

    Raises:
        ValueError: 用户不存在（调度器会按任务粒度 try/except 隔离）。
    """
    user = db.get(User, user_id)
    if user is None:
        raise ValueError(f"积分调整失败：用户不存在 user_id={user_id}")

    db.add(
        CreditLog(
            user_id=user_id,
            task_id=task_id,
            delta=int(delta),
            reason=reason,
        )
    )
    user.credits = int(user.credits or 0) + int(delta)
    db.flush()

    balance = int(user.credits)
    if commit:
        db.commit()
    logger.debug("积分调整 user_id=%s task_id=%s delta=%s balance=%s", user_id, task_id, delta, balance)
    return balance


def has_task_bonus(
    db: Session,
    user_id: int,
    task_id: int | None,
    reason_prefix: str = REASON_TASK_BONUS_PREFIX,
) -> bool:
    """判断某用户是否已获得某任务的完成奖励流水（验收加分幂等）。

    幂等键必须是 **(user_id, task_id, reason LIKE)** 三元组：同一任务有多名
    approved 成员时，只按 ``task_id`` 判重会让第二名及之后的成员被误跳过
    （P1 单负责人行为，已在 `C-APPLY@1` 作废）。

    Args:
        db: SQLAlchemy 会话。
        user_id: 被检查的用户。
        task_id: 关联任务（``None`` 时按「无任务关联」精确匹配）。
        reason_prefix: 流水原因前缀，默认「任务完成奖励」。

    Returns:
        已存在匹配流水返回 ``True``，否则 ``False``。
    """
    query = db.query(CreditLog.id).filter(
        CreditLog.user_id == int(user_id),
        CreditLog.reason.like(f"{reason_prefix}%"),
    )
    if task_id is None:
        query = query.filter(CreditLog.task_id.is_(None))
    else:
        query = query.filter(CreditLog.task_id == int(task_id))
    return db.query(query.exists()).scalar() is True


__all__ = [
    "adjust_credits",
    "has_task_bonus",
    "REASON_TASK_BONUS_PREFIX",
    "REASON_OVERDUE_PREFIX",
    "DEFAULT_CREDIT_REWARD",
    "OVERDUE_PENALTY",
]