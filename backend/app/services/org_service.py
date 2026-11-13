"""组织、成员、邀请与受控密码重置的唯一实现（契约 `C-ORG@1`）。

- 组织只有三种角色：``admin`` / ``collaborator`` / ``member``；``title`` 仅作展示，不派生权限。
- ``org admin`` 判定只认 ``org_members.role == 'admin' AND status == 'active'``。
- 邀请使用次数只在注册成功的同一事务内递增，并发靠 ``UPDATE ... WHERE used_count < max_uses``
  的 ``rowcount`` 判定（SQLite 写锁串行化）。
- 明文邀请令牌与重置令牌只在创建响应出现一次，库中只存 ``hash_token(token)``。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Invitation, Organization, OrgMember, PasswordReset, User
from app.schemas import InvitationCreatedOut, InvitationOut, MemberPatchIn, OrgCreateIn, OrgMemberOut, OrgMembershipOut, OrgOut, RegisterIn
from app.security import hash_password, hash_token, new_token
from app.services import session_service

ORG_ROLES: tuple[str, ...] = ("admin", "collaborator", "member")
MEMBER_STATUSES: tuple[str, ...] = ("active", "disabled")

RESET_TTL_MINUTES = 30
INVITE_TOKEN_BYTES = 32
RESET_TOKEN_BYTES = 32

ERR_BAD_REQUEST = 4001
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040


def _now() -> datetime:
    return datetime.now()


def _fmt(value: datetime) -> str:
    """与既有表一致的本地时间文本（``YYYY-MM-DD HH:MM:SS``），可直接做字符串比较。"""
    return value.strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# 组织
# --------------------------------------------------------------------------- #


def create_organization(db: Session, payload: OrgCreateIn) -> Organization:
    """创建组织（仅平台管理员可调用，权限由路由层校验）。"""
    name = payload.name.strip()
    slug = payload.slug.strip()
    if not name or not slug:
        raise ApiError(ERR_BAD_REQUEST, "组织名称不能为空")

    duplicated = db.scalar(
        select(Organization.id).where(
            or_(Organization.name == name, Organization.slug == slug)
        )
    )
    if duplicated is not None:
        raise ApiError(ERR_BAD_REQUEST, "组织已存在")

    org = Organization(
        name=name,
        slug=slug,
        status="active",
        created_at=_fmt(_now()),
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def org_payload(org: Organization) -> dict[str, Any]:
    return OrgOut.model_validate(
        {
            "id": int(org.id),
            "name": str(org.name),
            "slug": str(org.slug),
            "status": str(org.status),
            "created_at": str(org.created_at),
        }
    ).model_dump()


def list_memberships(db: Session, user: User) -> list[dict[str, Any]]:
    """该用户全部 ``active`` 组织成员关系，按组织名升序（单次 JOIN，无 N+1）。"""
    rows = db.execute(
        select(
            Organization.id,
            Organization.name,
            Organization.slug,
            OrgMember.role,
            OrgMember.title,
            OrgMember.status,
        )
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == int(user.id), OrgMember.status == "active")
        .order_by(Organization.name.asc(), Organization.id.asc())
    ).all()
    return [
        OrgMembershipOut.model_validate(
            {
                "org_id": int(org_id),
                "name": str(name),
                "slug": str(slug),
                "role": str(role),
                "title": title,
                "status": str(status),
            }
        ).model_dump()
        for org_id, name, slug, role, title, status in rows
    ]


def find_membership(db: Session, user_id: int, org_id: int) -> OrgMember | None:
    return db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == int(org_id), OrgMember.user_id == int(user_id)
        )
    )


def require_org_admin(db: Session, user: User, org_id: int) -> OrgMember:
    """非本组织成员按不存在处理（4040，不泄露组织存在性）；成员但非管理员 4030。"""
    membership = find_membership(db, int(user.id), int(org_id))
    if membership is None:
        raise ApiError(ERR_NOT_FOUND, "组织不存在", 404)
    if str(membership.status) != "active" or str(membership.role) != "admin":
        raise ApiError(ERR_FORBIDDEN, "无权操作该组织", 403)
    return membership


# --------------------------------------------------------------------------- #
# 成员
# --------------------------------------------------------------------------- #


def _member_payload(member: OrgMember, user: User) -> dict[str, Any]:
    return OrgMemberOut.model_validate(
        {
            "user_id": int(member.user_id),
            "username": str(user.username),
            "display_name": str(user.display_name),
            "role": str(member.role),
            "title": member.title,
            "status": str(member.status),
            "joined_at": str(member.created_at),
        }
    ).model_dump()


def list_members(db: Session, org_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(OrgMember, User)
        .join(User, User.id == OrgMember.user_id)
        .where(OrgMember.org_id == int(org_id))
        .order_by(OrgMember.created_at.asc(), OrgMember.id.asc())
    ).all()
    return [_member_payload(member, user) for member, user in rows]


def update_member(
    db: Session, org_id: int, user_id: int, payload: MemberPatchIn
) -> dict[str, Any]:
    """修改成员角色 / 职务 / 状态；最后一名 active admin 不可降级或停用。"""
    member = find_membership(db, user_id, org_id)
    if member is None:
        raise ApiError(ERR_NOT_FOUND, "成员不存在", 404)

    role = str(member.role)
    status = str(member.status)
    if payload.role is not None:
        if payload.role not in ORG_ROLES:
            raise ApiError(ERR_BAD_REQUEST, "组织角色不合法")
        role = payload.role
    if payload.status is not None:
        if payload.status not in MEMBER_STATUSES:
            raise ApiError(ERR_BAD_REQUEST, "成员状态不合法")
        status = payload.status

    loses_admin = (
        str(member.role) == "admin"
        and str(member.status) == "active"
        and (role != "admin" or status != "active")
    )
    if loses_admin:
        remaining = db.scalar(
            select(func.count())
            .select_from(OrgMember)
            .where(
                OrgMember.org_id == int(org_id),
                OrgMember.role == "admin",
                OrgMember.status == "active",
                OrgMember.id != int(member.id),
            )
        )
        if not remaining:
            raise ApiError(ERR_BAD_REQUEST, "组织至少保留一名管理员")

    member.role = role
    member.status = status
    if payload.title is not None:
        member.title = payload.title.strip() or None

    user = db.get(User, int(member.user_id))
    db.commit()
    db.refresh(member)
    if user is None:
        raise ApiError(ERR_NOT_FOUND, "成员不存在", 404)
    return _member_payload(member, user)


# --------------------------------------------------------------------------- #
# 邀请
# --------------------------------------------------------------------------- #


def _invitation_payload(invitation: Invitation) -> dict[str, Any]:
    return InvitationOut.model_validate(
        {
            "id": int(invitation.id),
            "org_id": int(invitation.org_id),
            "role_cap": str(invitation.role_cap),
            "expires_at": str(invitation.expires_at),
            "max_uses": int(invitation.max_uses),
            "used_count": int(invitation.used_count),
            "revoked_at": invitation.revoked_at,
            "created_at": str(invitation.created_at),
        }
    ).model_dump()


def create_invitation(
    db: Session, org_id: int, role_cap: str, expires_in_hours: int, max_uses: int, created_by: int
) -> tuple[Invitation, str]:
    """明文令牌只在返回值中出现一次，库中只存 ``hash_token``。"""
    if role_cap not in ORG_ROLES:
        raise ApiError(ERR_BAD_REQUEST, "组织角色不合法")

    token = new_token(INVITE_TOKEN_BYTES)
    now = _now()
    invitation = Invitation(
        org_id=int(org_id),
        role_cap=role_cap,
        token_hash=hash_token(token),
        expires_at=_fmt(now + timedelta(hours=int(expires_in_hours))),
        max_uses=int(max_uses),
        used_count=0,
        created_by=int(created_by),
        created_at=_fmt(now),
        revoked_at=None,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation, token


def invitation_created_payload(invitation: Invitation, token: str) -> dict[str, Any]:
    payload = _invitation_payload(invitation)
    payload["token"] = token
    return InvitationCreatedOut.model_validate(payload).model_dump()


def list_invitations(db: Session, org_id: int) -> list[dict[str, Any]]:
    invitations = db.scalars(
        select(Invitation)
        .where(Invitation.org_id == int(org_id))
        .order_by(Invitation.created_at.desc(), Invitation.id.desc())
    ).all()
    return [_invitation_payload(item) for item in invitations]


def revoke_invitation(db: Session, org_id: int, invitation_id: int) -> None:
    """已撤销的邀请再次撤销为幂等成功。"""
    invitation = db.scalar(
        select(Invitation).where(
            Invitation.id == int(invitation_id), Invitation.org_id == int(org_id)
        )
    )
    if invitation is None:
        raise ApiError(ERR_NOT_FOUND, "邀请不存在", 404)
    if invitation.revoked_at is None:
        invitation.revoked_at = _fmt(_now())
        db.commit()


# --------------------------------------------------------------------------- #
# 受控密码重置
# --------------------------------------------------------------------------- #


def issue_password_reset(db: Session, *, user_id: int, created_by: int) -> tuple[str, str]:
    """发放一次性、30 分钟有效的重置令牌；明文只在返回值中出现。"""
    user = db.get(User, int(user_id))
    if user is None:
        raise ApiError(ERR_NOT_FOUND, "用户不存在", 404)

    token = new_token(RESET_TOKEN_BYTES)
    now = _now()
    expires_at = _fmt(now + timedelta(minutes=RESET_TTL_MINUTES))
    db.add(
        PasswordReset(
            user_id=int(user.id),
            token_hash=hash_token(token),
            expires_at=expires_at,
            used_at=None,
            created_by=int(created_by),
            created_at=_fmt(now),
        )
    )
    db.commit()
    return token, expires_at


def reset_password(db: Session, token: str, password: str, confirm_password: str) -> None:
    """消费重置令牌：同一事务内标记一次性、改密码、撤销该用户全部会话。"""
    if password != confirm_password:
        raise ApiError(ERR_BAD_REQUEST, "两次输入的密码不一致")

    reset = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(token)))
    if reset is None:
        raise ApiError(ERR_BAD_REQUEST, "重置凭据无效或已过期")

    now = _fmt(_now())
    try:
        consumed = db.execute(
            update(PasswordReset)
            .where(
                PasswordReset.id == int(reset.id),
                PasswordReset.used_at.is_(None),
                PasswordReset.expires_at > now,
            )
            .values(used_at=now)
            .execution_options(synchronize_session=False)
        )
        if consumed.rowcount != 1:
            raise ApiError(ERR_BAD_REQUEST, "重置凭据无效或已过期")

        user = db.get(User, int(reset.user_id))
        if user is None:
            raise ApiError(ERR_BAD_REQUEST, "重置凭据无效或已过期")
        user.password_hash = hash_password(password)
        user.password_updated_at = now
        # 旧演示账号完成一次受控重置后才可登录（R7）；被停用的账号保持停用。
        if str(user.status) == "legacy_unclaimed":
            user.status = "active"
        session_service.revoke_user_sessions(db, int(user.id))
        db.commit()
    except Exception:
        db.rollback()
        raise


# --------------------------------------------------------------------------- #
# 邀请注册
# --------------------------------------------------------------------------- #


def register_user(db: Session, payload: RegisterIn) -> tuple[User, list[dict[str, Any]]]:
    """邀请原子消费 + 建号 + 建成员关系，同一事务；任一步失败整体回滚。"""
    if payload.password != payload.confirm_password:
        raise ApiError(ERR_BAD_REQUEST, "两次输入的密码不一致")

    invitation = db.scalar(
        select(Invitation).where(Invitation.token_hash == hash_token(payload.invite_token))
    )
    if invitation is None:
        raise ApiError(ERR_BAD_REQUEST, "邀请无效或已用尽")

    now = _fmt(_now())
    try:
        consumed = db.execute(
            update(Invitation)
            .where(
                Invitation.id == int(invitation.id),
                Invitation.used_count < Invitation.max_uses,
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > now,
            )
            .values(used_count=Invitation.used_count + 1)
            .execution_options(synchronize_session=False)
        )
        if consumed.rowcount != 1:
            raise ApiError(ERR_BAD_REQUEST, "邀请无效或已用尽")

        existing = db.scalar(select(User).where(User.username == payload.username))
        if existing is not None:
            # 旧演示账号绝不继承：同名注册一律拒绝，只能走管理员重置。
            if str(existing.status) == "legacy_unclaimed" or existing.password_hash is None:
                raise ApiError(ERR_BAD_REQUEST, "该账号为旧演示账号，需管理员重置后使用")
            raise ApiError(ERR_BAD_REQUEST, "账号已存在")

        display_name = payload.display_name.strip() or payload.username
        user = User(
            username=payload.username,
            display_name=display_name,
            password_hash=hash_password(payload.password),
            password_updated_at=now,
            status="active",
            platform_admin=0,
            credits=0,
            created_at=now,
        )
        db.add(user)
        db.flush()
        db.add(
            OrgMember(
                org_id=int(invitation.org_id),
                user_id=int(user.id),
                role=str(invitation.role_cap),
                title=None,
                status="active",
                created_at=now,
            )
        )
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(user)
    return user, list_memberships(db, user)


__all__ = [
    "ORG_ROLES",
    "MEMBER_STATUSES",
    "RESET_TTL_MINUTES",
    "create_organization",
    "org_payload",
    "list_memberships",
    "find_membership",
    "require_org_admin",
    "list_members",
    "update_member",
    "create_invitation",
    "invitation_created_payload",
    "list_invitations",
    "revoke_invitation",
    "issue_password_reset",
    "reset_password",
    "register_user",
]