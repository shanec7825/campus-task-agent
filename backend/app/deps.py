"""Cookie 会话鉴权依赖（契约 `C-SESSION@1`，owner = T2）。

身份只来自 HttpOnly Cookie ``cta_session``；不再接受 ``Authorization`` 头或 ``?token=``。
``require_csrf`` 使用双提交校验：Cookie ``cta_csrf`` 与请求头 ``X-CSRF-Token`` 相等，
且等于该会话记录中的 ``csrf_token``。
"""

from __future__ import annotations

import hmac

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.services.session_service import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    resolve_session,
)

# 认证失败统一文案与错误码（`2.2.4` 错误码总表：4010 未登录 / 4030 越权）
ERROR_UNAUTHORIZED = 4010
MESSAGE_UNAUTHORIZED = "未登录或登录已过期"
ERROR_CSRF = 4030
MESSAGE_CSRF = "CSRF 校验失败"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def unauthorized() -> ApiError:
    """构造统一的 4010 异常（HTTP 401）。"""
    return ApiError(ERROR_UNAUTHORIZED, MESSAGE_UNAUTHORIZED, 401)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """解析 ``cta_session`` Cookie；缺失 / 过期 / 已撤销 / 用户非 active ⇒ 401 + ``code=4010``。"""
    resolved = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if resolved is None:
        raise unauthorized()
    return resolved[0]


def get_sse_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """SSE 专用：``EventSource`` 由浏览器自动携带 Cookie，``?token=`` 参数被忽略。"""
    return get_current_user(request, db)


def require_csrf(request: Request, db: Session = Depends(get_db)) -> None:
    """写操作 CSRF 校验；安全方法与未登录请求直接放行。

    无有效会话时不在此拦截：未登录的写请求交由 :func:`get_current_user`
    统一返回 ``4010``，避免无 Cookie 时被误报为 CSRF 失败。
    """
    if request.method in _SAFE_METHODS:
        return
    resolved = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if resolved is None:
        return
    cookie_token = request.cookies.get(CSRF_COOKIE) or ""
    header_token = request.headers.get(CSRF_HEADER) or ""
    if not cookie_token or not hmac.compare_digest(cookie_token, header_token):
        raise ApiError(ERROR_CSRF, MESSAGE_CSRF, 403)
    if not hmac.compare_digest(cookie_token, resolved[1].csrf_token):
        raise ApiError(ERROR_CSRF, MESSAGE_CSRF, 403)


__all__ = [
    "ERROR_UNAUTHORIZED",
    "MESSAGE_UNAUTHORIZED",
    "get_current_user",
    "get_sse_current_user",
    "require_csrf",
    "unauthorized",
]