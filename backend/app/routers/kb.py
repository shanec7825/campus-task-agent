"""知识库路由（契约 `C-KB@1`，owner = T3）。

``GET /api/kb/similar?q=`` → ``{"items":[SimilarItem], "threshold":0.6}``

* 排序：``similarity DESC, id DESC``，最多 3 条（``find_similar`` 内保证）；
* 过滤：默认只返回 ``similarity >= 0.6``（前端据此展示"检测到相似任务"提示条），
  可用环境变量 ``KB_MIN_SIMILARITY`` 覆盖；设为 ``<= 0`` 则恢复 plan `2.2.8`
  的"后端不过滤，只返回 similarity > 0"行为。
* ``threshold`` 字段恒为 0.6（前端展示判断用，不受过滤开关影响）。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import ApiError, ok
from app.models import User
from app.services import kb_service

router = APIRouter(prefix="/api/kb", tags=["kb"])

TOP_N = 3
MAX_QUERY_LENGTH = 500


def _min_similarity() -> float | None:
    """读取过滤阈值：默认 0.6；``<= 0`` 表示不过滤（plan 2.2.8 原样）。"""
    raw = (os.getenv("KB_MIN_SIMILARITY") or "").strip()
    if not raw:
        return kb_service.SIMILARITY_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        return kb_service.SIMILARITY_THRESHOLD
    return None if value <= 0 else value


@router.get("/similar")
def similar(
    q: str = Query(default="", max_length=MAX_QUERY_LENGTH, description="任务标题或部分内容"),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    """相似任务检索（top3，降序）。"""
    query = (q or "").strip()
    if not query:
        raise ApiError(4001, "查询文本不能为空")

    items = kb_service.find_similar(db, query, top_n=TOP_N, min_similarity=_min_similarity())
    return ok(
        {
            "items": [item.model_dump() for item in items],
            "threshold": kb_service.SIMILARITY_THRESHOLD,
        }
    )


__all__ = ["router"]