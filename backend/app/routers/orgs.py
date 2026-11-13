"""组织、成员、邀请与受控密码重置路由（契约 `C-ORG@1`，owner = T3）。

路由集中在单文件、单 ``router``（`main.py` 只挂载 ``routers.orgs.router``）：
组织创建、成员管理、邀请生命周期、组织管理员与平台管理员的密码重置。

权限：组织内操作只认 ``org_members.role == 'admin' AND status == 'active'``；
``GET/PATCH/DELETE`` 之外的写操作同样受 CSRF 双提交校验（`C-SESSION@1`）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf
from app.errors import ApiError, ok
from app.models import User
from app.schemas import (
    InvitationCreateIn,
    MemberPatchIn,
    OrgCreateIn,
    PasswordResetRequestOut,
)
from app.services import org_service

router = APIRouter(tags=["orgs"])

ERR_FORBIDDEN = 4030


def _require_platform_admin(user: User) -> None:
    if not bool(user.platform_admin):
        raise ApiError(ERR_FORBIDDEN, "需要平台管理员权限", 403)


@router.get("/api/orgs/mine")
def list_my_orgs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok({"items": org_service.list_memberships(db, current_user)})


@router.post("/api/orgs")
def create_org(
    payload: OrgCreateIn,
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_platform_admin(current_user)
    org = org_service.create_organization(db, payload)
    return ok(org_service.org_payload(org))


@router.get("/api/orgs/{org_id}/members")
def list_org_members(
    org_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_service.require_org_admin(db, current_user, org_id)
    return ok({"items": org_service.list_members(db, org_id)})


@router.patch("/api/orgs/{org_id}/members/{user_id}")
def patch_org_member(
    org_id: int,
    user_id: int,
    payload: MemberPatchIn,
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_service.require_org_admin(db, current_user, org_id)
    return ok(org_service.update_member(db, org_id, user_id, payload))


@router.post("/api/orgs/{org_id}/invitations")
def create_org_invitation(
    org_id: int,
    payload: InvitationCreateIn,
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_service.require_org_admin(db, current_user, org_id)
    invitation, token = org_service.create_invitation(
        db,
        org_id,
        payload.role_cap,
        payload.expires_in_hours,
        payload.max_uses,
        int(current_user.id),
    )
    return ok(org_service.invitation_created_payload(invitation, token))


@router.get("/api/orgs/{org_id}/invitations")
def list_org_invitations(
    org_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_service.require_org_admin(db, current_user, org_id)
    return ok({"items": org_service.list_invitations(db, org_id)})


@router.post("/api/orgs/{org_id}/invitations/{invitation_id}/revoke")
def revoke_org_invitation(
    org_id: int,
    invitation_id: int,
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_service.require_org_admin(db, current_user, org_id)
    org_service.revoke_invitation(db, org_id, invitation_id)
    return ok({"revoked": True})


@router.post("/api/orgs/{org_id}/members/{user_id}/password-reset")
def reset_member_password(
    org_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """组织管理员为本组织 active 成员发放一次性重置令牌（30 分钟）。"""
    org_service.require_org_admin(db, current_user, org_id)
    membership = org_service.find_membership(db, user_id, org_id)
    if membership is None or str(membership.status) != "active":
        raise ApiError(4040, "成员不存在", 404)
    token, expires_at = org_service.issue_password_reset(
        db, user_id=user_id, created_by=int(current_user.id)
    )
    return ok(PasswordResetRequestOut(token=token, expires_at=expires_at).model_dump())


@router.post("/api/admin/users/{user_id}/password-reset")
def admin_reset_password(
    user_id: int,
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """平台管理员为用户发放一次性重置令牌（不读现有密码）。"""
    _require_platform_admin(current_user)
    token, expires_at = org_service.issue_password_reset(
        db, user_id=user_id, created_by=int(current_user.id)
    )
    return ok(PasswordResetRequestOut(token=token, expires_at=expires_at).model_dump())


__all__ = ["router"]