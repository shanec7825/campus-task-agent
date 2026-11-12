"""积分路由（契约 `C-TASKS@1` #13，owner = T2）。

``GET /api/credits/me`` 返回当前余额与全部流水（``created_at DESC, id DESC``），
并校验「余额 == 流水之和」；不一致只记日志、不改数据（R6-AC5）。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import ok
from app.models import CreditLog, User
from app.schemas import CreditLogOut, CreditsMeOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/credits", tags=["credits"])


@router.get("/me")
def my_credits(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """我的积分：余额 + 全部流水。"""
    logs = (
        db.query(CreditLog)
        .filter(CreditLog.user_id == current_user.id)
        .order_by(CreditLog.created_at.desc(), CreditLog.id.desc())
        .all()
    )

    balance = int(current_user.credits or 0)
    log_sum = sum(int(log.delta) for log in logs)
    if log_sum != balance:
        # 只记日志不改数据：Demo 期允许人工干预积分，但必须留下可观测痕迹
        logger.warning(
            "积分余额与流水之和不一致 user_id=%s credits=%s sum=%s",
            current_user.id,
            balance,
            log_sum,
        )

    data = CreditsMeOut(
        credits=balance,
        logs=[CreditLogOut.model_validate(log) for log in logs],
    ).model_dump()
    return ok(data)


__all__ = ["router"]