"""通知路由（契约 `C-NOTIFY@1`，owner = T2）。

包含三件事：
1. ``GET /api/notifications``：当前用户的通知列表（未读数 + 历史）；
2. ``POST /api/notifications/read``：批量标记已读（只影响自己的记录）；
3. ``GET /api/notifications/stream``：SSE 长连接。

SSE 实现要点（跨 T2/T4）：
- 鉴权只走 Cookie（``get_sse_current_user``）；``?token=`` 参数被忽略，不参与鉴权；
- 数据来源**只能**是 ``notification_hub.subscribe/unsubscribe``（连接注册表 owner = T4），
  本模块不维护任何自己的连接集合；
- 心跳注释行 ``": ping\\n\\n"`` 的间隔取 ``SSE_HEARTBEAT_SECONDS``；
- 事件名固定 ``notify``，``data`` 行为单行 JSON，事件之间空行分隔；
- 连接建立后不重放历史（历史由列表接口获取）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from datetime import datetime

from app.db import get_db
from app.deps import get_current_user, get_sse_current_user, require_csrf
from app.errors import ApiError, ok
from app.models import Notification, Task, User
from app.schemas import ArchiveIn, NotificationListOut, NotificationOut, ReadIn
from app.services import authz, notification_hub

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_csrf)],
)

# SSE 默认心跳间隔（与 `C-BOOT@1` 环境变量表一致）
DEFAULT_SSE_HEARTBEAT_SECONDS = 15.0
DEFAULT_LIST_LIMIT = 50


def _heartbeat_seconds() -> float:
    """读取心跳间隔；非法值回退默认，避免单条脏配置导致 SSE 连接异常。"""
    raw = os.getenv("SSE_HEARTBEAT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_SSE_HEARTBEAT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning("SSE_HEARTBEAT_SECONDS 非法（%s），回退默认 %.1fs", raw, DEFAULT_SSE_HEARTBEAT_SECONDS)
        return DEFAULT_SSE_HEARTBEAT_SECONDS
    return value if value > 0 else DEFAULT_SSE_HEARTBEAT_SECONDS


@router.get("")
def list_notifications(
    unread_only: bool = Query(default=False),
    archived: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """通知列表：``unread`` 只统计未归档的有效未读；``archived`` 切换归档箱。"""
    unread = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.archived == 0,
            Notification.is_read == 0,
            Notification.stale == 0,
        )
        .count()
    )

    query = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.archived == (1 if archived else 0),
    )
    if unread_only:
        query = query.filter(Notification.is_read == 0, Notification.stale == 0)
    total = query.count()
    rows = (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # 关联任务不可见时只保留标题与 task_id，不回吐任务正文（`C-OTHER-AUTH@1`）
    task_ids = {int(row.task_id) for row in rows if row.task_id is not None}
    visible_task_ids: set[int] = set()
    if task_ids:
        tasks = db.query(Task).filter(Task.id.in_(task_ids)).all()
        visible_task_ids = {
            int(task.id) for task in tasks if authz.can_view_task(db, current_user, task)
        }

    items = []
    for row in rows:
        item = NotificationOut.model_validate(row)
        if row.task_id is not None and int(row.task_id) not in visible_task_ids:
            item.content = ""
        items.append(item)

    data = NotificationListOut(unread=int(unread), total=int(total), items=items).model_dump()
    return ok(data)


@router.post("/read")
def read_notifications(
    payload: ReadIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """批量标记已读：一次 ``UPDATE ... WHERE id IN (...) AND user_id=...``。"""
    ids = [int(item) for item in payload.ids]
    if not ids:
        return ok({"updated": 0})

    updated = (
        db.query(Notification)
        .filter(
            Notification.id.in_(ids),
            Notification.user_id == current_user.id,
            Notification.is_read == 0,
            Notification.stale == 0,
        )
        .update({Notification.is_read: 1}, synchronize_session=False)
    )
    db.commit()
    return ok({"updated": int(updated or 0)})


@router.post("/archive")
def archive_notifications(
    payload: ArchiveIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """归档通知（`C-NOTICE-ARCHIVE@1`）：只处理本人未归档记录，重复调用幂等。"""
    ids = [int(item) for item in payload.ids]
    if not ids:
        raise ApiError(4001, "请选择要归档的通知")

    archived_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated = (
        db.query(Notification)
        .filter(
            Notification.id.in_(ids),
            Notification.user_id == current_user.id,
            Notification.archived == 0,
        )
        .update(
            {Notification.archived: 1, Notification.archived_at: archived_at},
            synchronize_session=False,
        )
    )
    db.commit()
    return ok({"updated": int(updated or 0)})


def _format_sse_event(payload: dict[str, Any]) -> str:
    """把通知 payload 渲染为单行 ``event: notify`` 事件（逐字符合 `C-NOTIFY@1`）。"""
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: notify\ndata: {data}\n\n"


async def _event_source(user_id: int) -> AsyncIterator[str]:
    """SSE 事件生成器：先注册队列，退出时务必注销（防止连接泄漏）。"""
    queue = notification_hub.subscribe(user_id)
    heartbeat = _heartbeat_seconds()
    try:
        yield ": ping\n\n"  # 立即回一帧，避免部分客户端等待首个事件超时
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            yield _format_sse_event(payload)
    except asyncio.CancelledError:  # 客户端断开
        raise
    finally:
        notification_hub.unsubscribe(user_id, queue)


@router.get("/stream")
async def stream_notifications(
    current_user: User = Depends(get_sse_current_user),
) -> StreamingResponse:
    """SSE 长连接：仅 Cookie 鉴权（``get_sse_current_user``），事件名 ``notify``，空闲时发送心跳。"""
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        _event_source(int(current_user.id)),
        media_type="text/event-stream; charset=utf-8",
        headers=headers,
    )


__all__ = ["router"]