"""认证路由（契约 `C-AUTH@1`，owner = T2）。

- ``POST /api/auth/login``：首次登录自动建号，返回 ``{token, user}``；
- ``GET /api/auth/me``：前端刷新页面后恢复会话。

角色规则（R1-AC2）：``teacher*`` → ``publisher``、``admin*`` → ``admin``、
其余 → ``student``。``teacher01`` / ``student01`` / ``student02`` / ``student03``
在首次登录时即自动可用，无需任何预置数据（R1-AC3）。
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, register_token
from app.errors import ApiError, ok
from app.models import User
from app.schemas import LoginIn, LoginOut, UserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 演示账号的中文展示名（不在映射内则取 username，见 `2.2.3` 第 2 条）
DISPLAY_NAME_MAP: dict[str, str] = {
    "teacher01": "王老师",
    "student01": "李同学",
    "student02": "张同学",
    "student03": "陈同学",
}

# 错误码（`2.2.4` 错误码总表：4001 参数校验失败）
ERROR_INVALID_PARAM = 4001


def resolve_role(username: str) -> str:
    """按用户名前缀判定角色（R1-AC2）。"""
    if username.startswith("teacher"):
        return "publisher"
    if username.startswith("admin"):
        return "admin"
    return "student"


def _get_or_create_user(db: Session, username: str) -> User:
    """按用户名查用户，不存在则按契约默认值创建（R1-AC1）。"""
    user = db.query(User).filter(User.username == username).first()
    if user is not None:
        return user

    user = User(
        username=username,
        display_name=DISPLAY_NAME_MAP.get(username, username),
        role=resolve_role(username),
        org=None,
        credits=0,
    )
    db.add(user)
    try:
        db.commit()
    except Exception:
        # 并发首登可能撞唯一约束：回滚后按已存在的用户返回，不报错
        db.rollback()
        existing = db.query(User).filter(User.username == username).first()
        if existing is None:
            raise
        return existing
    db.refresh(user)
    logger.info("首次登录自动建号 username=%s role=%s", user.username, user.role)
    return user


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """登录（不鉴权）：首次调用自动建用户，重复登录不覆盖旧 token。"""
    username = payload.username.strip()
    if not username:
        raise ApiError(ERROR_INVALID_PARAM, "用户名不能为空")

    user = _get_or_create_user(db, username)

    # 允许多 token 并存：同一用户重复登录不覆盖旧 token（`2.2.3` 第 4 条）
    token = secrets.token_urlsafe(24)
    register_token(token, user.id)

    data = LoginOut(token=token, user=UserOut.model_validate(user)).model_dump()
    return ok(data)


@router.get("/me")
def me(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """返回当前 token 对应的用户，用于前端刷新页面后恢复会话。"""
    return ok(UserOut.model_validate(current_user).model_dump())


__all__ = ["router", "DISPLAY_NAME_MAP", "resolve_role"]