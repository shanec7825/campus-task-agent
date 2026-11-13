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
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import ApiError, ok
from app.models import KbEntry, Task, User
from app.schemas import SimilarItem
from app.services import authz, kb_service

router = APIRouter(prefix="/api/kb", tags=["kb"])

TOP_N = 3
MAX_QUERY_LENGTH = 500


def _visible_task_ids(db: Session, user: User):
    """知识库可见范围子查询：组织在用户所属组织内，或 ``org_id IS NULL`` 且由本人发布。"""
    org_ids = authz.org_ids_for(db, user)
    conditions = [and_(Task.org_id.is_(None), Task.publisher_id == user.id)]
    if org_ids:
        conditions.append(Task.org_id.in_(org_ids))
    return select(Task.id).where(or_(*conditions))


def _find_similar_scoped(
    db: Session,
    user: User,
    query: str,
    *,
    top_n: int,
    min_similarity: float | None,
) -> list[SimilarItem]:
    """与 ``kb_service.find_similar`` 同口径排序，但先把候选条目限定在可见任务内。"""
    entries = (
        db.query(KbEntry)
        .filter(KbEntry.task_id.in_(_visible_task_ids(db, user)))
        .all()
    )

    scored: list[tuple[int, SimilarItem]] = []
    for entry in entries:
        similarity = kb_service.score_pair(query, entry)["similarity"]
        if similarity <= 0:
            continue
        if min_similarity is not None and similarity < min_similarity:
            continue
        scored.append(
            (
                entry.id,
                SimilarItem(
                    task_id=entry.task_id,
                    title=entry.title,
                    summary=entry.summary,
                    similarity=similarity,
                    created_at=entry.created_at,
                ),
            )
        )

    scored.sort(key=lambda item: (item[1].similarity, item[0]), reverse=True)
    return [item[1] for item in scored[: max(1, top_n)]]


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
    current_user: User = Depends(get_current_user),
) -> dict:
    """相似任务检索（top3，降序），只检索当前用户可见任务范围内的条目。"""
    query = (q or "").strip()
    if not query:
        raise ApiError(4001, "查询文本不能为空")

    items = _find_similar_scoped(
        db,
        current_user,
        query,
        top_n=TOP_N,
        min_similarity=_min_similarity(),
    )
    return ok(
        {
            "items": [item.model_dump() for item in items],
            "threshold": kb_service.SIMILARITY_THRESHOLD,
        }
    )


__all__ = ["router"]