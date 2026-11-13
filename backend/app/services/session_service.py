"""服务端会话、Cookie 与 CSRF（契约 `C-SESSION@1`，owner = T2）。

会话落库到 ``user_sessions``：库中只存 ``hash_token(token)``，明文只出现在下发 Cookie 的那一次
响应中。``cta_session`` 为 HttpOnly 会话 Cookie，``cta_csrf`` 为非 HttpOnly 的双提交令牌。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import Response
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import User, UserSession
from app.security import hash_token, new_token

SESSION_COOKIE = "cta_session"
CSRF_COOKIE = "cta_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL_HOURS = 168

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def _now() -> datetime:
    return datetime.now()


def _fmt(moment: datetime) -> str:
    return moment.strftime(_TS_FORMAT)


def _secure_cookies() -> bool:
    return os.getenv("COOKIE_SECURE", "0").strip() == "1"


def create_session(db: Session, user_id: int) -> tuple[str, str]:
    """新建会话并落库，返回 ``(session_token, csrf_token)``；令牌已提交前不得写日志。"""
    session_token = new_token(32)
    csrf_token = new_token(24)
    now = _now()
    db.add(
        UserSession(
            user_id=user_id,
            token_hash=hash_token(session_token),
            csrf_token=csrf_token,
            created_at=_fmt(now),
            expires_at=_fmt(now + timedelta(hours=SESSION_TTL_HOURS)),
            last_seen_at=_fmt(now),
        )
    )
    db.commit()
    return session_token, csrf_token


def resolve_session(db: Session, token: str | None) -> tuple[User, UserSession] | None:
    """按明文令牌解析会话；过期、已撤销、用户非 ``active`` 一律视为未登录。"""
    if not token:
        return None
    row = db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).first()
    if row is None:
        return None
    now = _fmt(_now())
    if row.revoked_at or row.expires_at <= now:
        return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    try:
        row.last_seen_at = now
        db.commit()
    except Exception:  # noqa: BLE001 - last_seen_at 是弱一致字段，写失败不得影响请求
        db.rollback()
    return user, row


def revoke_session(db: Session, token: str | None) -> bool:
    """撤销单个会话；不存在或已撤销返回 ``False``（退出接口幂等）。"""
    if not token:
        return False
    row = db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).first()
    if row is None or row.revoked_at:
        return False
    row.revoked_at = _fmt(_now())
    db.commit()
    return True


def revoke_user_sessions(db: Session, user_id: int, *, except_token: str | None = None) -> int:
    """撤销某用户全部未撤销会话，返回撤销行数；``except_token`` 用于保留当前管理员的会话。"""
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_fmt(_now()))
        .execution_options(synchronize_session=False)
    )
    if except_token:
        stmt = stmt.where(UserSession.token_hash != hash_token(except_token))
    result = db.execute(stmt)
    db.commit()
    return int(result.rowcount or 0)


def set_session_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    """下发会话与 CSRF Cookie；``cta_csrf`` 必须可被前端 JS 读取（非 HttpOnly）。"""
    max_age = SESSION_TTL_HOURS * 3600
    secure = _secure_cookies()
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        samesite="lax",
        path="/",
        secure=secure,
    )


def clear_session_cookies(response: Response) -> None:
    """清除两个 Cookie（退出、重置与 401 响应共用）。"""
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


__all__ = [
    "SESSION_COOKIE",
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_TTL_HOURS",
    "create_session",
    "resolve_session",
    "revoke_session",
    "revoke_user_sessions",
    "set_session_cookies",
    "clear_session_cookies",
]