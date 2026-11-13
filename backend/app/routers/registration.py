"""邀请注册与一次性密码重置路由（契约 `C-ORG@1` / `C-AUTH-API@1`，owner = T3）。

两个端点都在无会话状态下调用，因此豁免 CSRF 双提交校验：
- ``POST /api/auth/register``：邀请原子消费 + 建号 + 建成员关系，成功后同请求内建会话；
- ``POST /api/auth/reset-password``：一次性令牌消费 + 改密码 + 撤销该用户全部会话。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ok
from app.schemas import LoginOut, OrgMembershipOut, PasswordResetIn, RegisterIn, UserOut
from app.services import org_service, session_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(
    payload: RegisterIn,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user, orgs = org_service.register_user(db, payload)
    session_token, csrf_token = session_service.create_session(db, int(user.id))
    session_service.set_session_cookies(response, session_token, csrf_token)
    return ok(
        LoginOut(
            user=UserOut.model_validate(user),
            orgs=[OrgMembershipOut.model_validate(item) for item in orgs],
        ).model_dump()
    )


@router.post("/reset-password")
def reset_password(payload: PasswordResetIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    org_service.reset_password(
        db, payload.token, payload.password, payload.confirm_password
    )
    return ok({"reset": True})


__all__ = ["router"]