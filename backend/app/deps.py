"""认证依赖（契约 `C-AUTH@1` / `C-BOOT@1` 第 6 条，最终 owner = T2）。

token 只存放在进程内存字典 :data:`TOKENS` 中，不落库、不设过期；进程重启后
所有旧 token 失效并返回 ``code=4010``（R1-AC5）。

除 :func:`get_current_user`（Authorization 头）外，本模块额外提供
:func:`get_sse_current_user`：``EventSource`` 无法携带自定义请求头，SSE 端点
按 `2.3 D3` 允许 ``?token=`` 查询参数鉴权，两者任一有效即可（`C-NOTIFY@1`）。
"""

from __future__ import annotations

from fastapi import Depends, Header, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import User

# token -> user_id；不落库、不设过期（R1-AC5）
TOKENS: dict[str, int] = {}

# 认证失败统一文案与错误码（`2.2.4` 错误码总表：4010 未登录）
ERROR_UNAUTHORIZED = 4010
MESSAGE_UNAUTHORIZED = "未登录或登录已过期"


def unauthorized() -> ApiError:
    """构造统一的 4010 异常（HTTP 401）。"""
    return ApiError(ERROR_UNAUTHORIZED, MESSAGE_UNAUTHORIZED, 401)


def register_token(token: str, user_id: int) -> None:
    """登记 token。同一用户允许持有多个 token（HTTP 与 SSE 可各自持有）。"""
    TOKENS[token] = user_id


def extract_bearer_token(authorization: str | None) -> str | None:
    """从 ``Authorization: Bearer <token>`` 中提取 token；格式不符返回 ``None``。"""
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization[len(prefix) :].strip()
    return token or None


def get_user_by_token(db: Session, token: str | None) -> User | None:
    """按 token 解析用户；token 缺失 / 未登记 / 用户已不存在均返回 ``None``。"""
    if not token:
        return None
    user_id = TOKENS.get(token)
    if user_id is None:
        return None
    return db.get(User, user_id)


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """从 ``Authorization: Bearer <token>`` 解析当前用户。

    缺 header / 非 ``Bearer `` 前缀 / token 未登记 / 用户不存在 ⇒ 401 + ``code=4010``。
    """
    user = get_user_by_token(db, extract_bearer_token(authorization))
    if user is None:
        raise unauthorized()
    return user


def get_sse_current_user(
    token: str | None = Query(default=None, description="SSE 专用：EventSource 无法携带请求头"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """SSE 端点专用鉴权：``?token=`` 查询参数与 ``Authorization`` 头二者其一有效即可。"""
    candidate = token.strip() if token else None
    if not candidate:
        candidate = extract_bearer_token(authorization)
    user = get_user_by_token(db, candidate)
    if user is None:
        raise unauthorized()
    return user


__all__ = [
    "TOKENS",
    "register_token",
    "extract_bearer_token",
    "get_user_by_token",
    "get_current_user",
    "get_sse_current_user",
    "unauthorized",
]