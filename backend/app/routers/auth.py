"""认证路由（契约 `C-AUTH-API@1` / `C-SESSION@1`，owner = T2）。

- ``POST /api/auth/login``：账号密码登录，成功下发 ``cta_session`` 与 ``cta_csrf``；
- ``POST /api/auth/logout``：撤销当前会话并清 Cookie（无会话时幂等返回）；
- ``GET /api/auth/me``：前端刷新后恢复会话，带该用户 active 组织成员关系。

登录失败按同一 IP + 用户名做进程内滑动窗口限流；失败文案不区分「账号不存在」与
「密码错误」（R1 不泄露账号是否存在）。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf
from app.errors import ApiError, ok
from app.models import User
from app.schemas import LoginIn, LoginOut, MeOut, OrgMembershipOut, UserOut
from app.security import hash_token, verify_password
from app.services import session_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

ERROR_LOGIN_FAILED = 4010
ERROR_TOO_MANY_ATTEMPTS = 4030
MESSAGE_LOGIN_FAILED = "账号或密码错误"
MESSAGE_LEGACY_UNCLAIMED = "该账号为旧演示账号，需管理员重置后使用"
MESSAGE_TOO_MANY_ATTEMPTS = "尝试过于频繁，请稍后再试"

LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_FAILURES = 5

# 限流键 -> 窗口内的失败时间戳（monotonic 秒）
_FAILURES: dict[str, list[float]] = {}

# 组织成员关系按冻结的表名/列名直查：只依赖 `C-DATA-AUTH@1`，不绑定 T1 的模型类名。
_MEMBERSHIPS_SQL = text(
    """
    SELECT m.org_id AS org_id,
           o.name AS name,
           o.slug AS slug,
           m.role AS role,
           m.title AS title,
           m.status AS status
      FROM org_members AS m
      JOIN organizations AS o ON o.id = m.org_id
     WHERE m.user_id = :user_id
       AND m.status = 'active'
     ORDER BY o.name ASC
    """
)


def _memberships(db: Session, user_id: int) -> list[OrgMembershipOut]:
    rows = db.execute(_MEMBERSHIPS_SQL, {"user_id": user_id}).mappings().all()
    return [OrgMembershipOut(**dict(row)) for row in rows]


def _limit_key(request: Request, username: str) -> str:
    client_ip = request.client.host if request.client else ""
    return f"{client_ip}|{hash_token(username)}"


def _recent_failures(key: str, now: float) -> list[float]:
    timestamps = [ts for ts in _FAILURES.get(key, []) if now - ts < LOGIN_WINDOW_SECONDS]
    if timestamps:
        _FAILURES[key] = timestamps
    else:
        _FAILURES.pop(key, None)
    return timestamps


def _is_rate_limited(key: str, now: float) -> bool:
    return len(_recent_failures(key, now)) >= LOGIN_MAX_FAILURES


def _record_failure(key: str, now: float) -> None:
    _recent_failures(key, now)
    _FAILURES.setdefault(key, []).append(now)


def _reset_failures(key: str) -> None:
    _FAILURES.pop(key, None)


@router.post("/login")
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """账号密码登录（无会话时本就无 CSRF 可校验，故不做 CSRF 要求）。"""
    username = payload.username.strip()
    key = _limit_key(request, username)
    now = time.monotonic()
    if _is_rate_limited(key, now):
        raise ApiError(ERROR_TOO_MANY_ATTEMPTS, MESSAGE_TOO_MANY_ATTEMPTS, 429)

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        _record_failure(key, now)
        raise ApiError(ERROR_LOGIN_FAILED, MESSAGE_LOGIN_FAILED, 401)
    if user.status == "legacy_unclaimed":
        _record_failure(key, now)
        raise ApiError(ERROR_LOGIN_FAILED, MESSAGE_LEGACY_UNCLAIMED, 401)
    if user.status != "active" or not verify_password(payload.password, user.password_hash):
        # disabled 与密码错误共用同一文案，避免泄露账号状态
        _record_failure(key, now)
        raise ApiError(ERROR_LOGIN_FAILED, MESSAGE_LOGIN_FAILED, 401)

    session_token, csrf_token = session_service.create_session(db, user.id)
    session_service.set_session_cookies(response, session_token, csrf_token)
    _reset_failures(key)

    data = LoginOut(user=UserOut.model_validate(user), orgs=_memberships(db, user.id)).model_dump()
    return ok(data)


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """撤销当前会话；无会话时同样返回 ``revoked=False``，便于前端无条件清理本地状态。"""
    token = request.cookies.get(session_service.SESSION_COOKIE)
    revoked = session_service.revoke_session(db, token)
    session_service.clear_session_cookies(response)
    return ok({"revoked": revoked})


@router.get("/me")
def me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """返回当前用户与组织成员关系，供前端刷新页面后恢复会话。"""
    data = MeOut(
        user=UserOut.model_validate(current_user),
        orgs=_memberships(db, current_user.id),
    ).model_dump()
    return ok(data)


__all__ = ["router"]