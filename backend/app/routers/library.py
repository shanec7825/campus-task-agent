"""Library 私有参考链接路由（契约 `C-LIBRARY@1`，设计 §9.2）。

只提供本人链接的列表 / 新增 / 更新；所有者始终来自当前会话，
不提供 DELETE、公开共享或跨账号读写。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf
from app.errors import ok
from app.models import User
from app.schemas import LibraryLinkCreateIn, LibraryLinkUpdateIn
from app.services import library_service

router = APIRouter(
    prefix="/api/library", tags=["library"], dependencies=[Depends(require_csrf)]
)


@router.get("/links")
def list_links(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(
        default=library_service.DEFAULT_LIMIT,
        ge=1,
        le=library_service.MAX_LIMIT,
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """当前用户的个人链接分页列表。"""
    rows, total = library_service.list_links(db, current_user, offset=offset, limit=limit)
    return ok(
        {
            "items": [library_service.to_out(row).model_dump() for row in rows],
            "total": total,
        }
    )


@router.post("/links")
def create_link(
    payload: LibraryLinkCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """新增本人链接；非法 scheme / 超长字段返回 4001。"""
    row = library_service.create_link(db, current_user, payload)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return ok(library_service.to_out(row).model_dump())


@router.patch("/links/{link_id}")
def update_link(
    link_id: int,
    payload: LibraryLinkUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """更新本人链接元数据；非本人或不存在统一 4040。"""
    row = library_service.update_link(db, current_user, link_id, payload)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return ok(library_service.to_out(row).model_dump())


__all__ = ["router"]