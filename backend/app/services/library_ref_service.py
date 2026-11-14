"""Library 引用式收藏服务（契约 `C-LIB-REF@1`）。

* 引用只存 ``(owner_id, resource_id)`` 与时间戳，不复制文件、不缓存正文；
* 可见性实时判定：``allow_student_ai=1``、``archived=0`` 且资料所属组织在当前
  用户的组织范围内；不满足即视为不可访问，对外统一 ``4040``；
* ``record_citations`` 供 AI 回答后调用，失败只记日志，绝不影响回答返回。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import LibraryRef, OrgResource, User
from app.schemas import LibraryRefOut
from app.services import authz

logger = logging.getLogger(__name__)

ERR_NOT_FOUND = 4040


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_out(ref: LibraryRef, resource: OrgResource) -> LibraryRefOut:
    """引用 + 资料快照的公开序列化入口。"""
    return LibraryRefOut(
        resource_id=int(resource.id),
        title=resource.title,
        summary=resource.summary,
        resource_type=resource.resource_type,
        file_name=resource.file_name,
        file_size=resource.file_size,
        url=resource.url,
        org_id=int(resource.org_id),
        added_at=ref.added_at,
        last_used_at=ref.last_used_at,
    )


def _accessible_resources(
    db: Session, user: User, resource_ids: Iterable[int]
) -> dict[int, OrgResource]:
    """引用可见性的唯一判定：开关开启、未归档、且资料组织在当前用户的组织范围内。

    ``list_refs`` / ``save_ref`` / ``record_citations`` / ``has_active_ref`` 共用，
    避免列表与下载对同一份资料给出不同结论。
    """
    ids = {int(item) for item in resource_ids}
    if not ids:
        return {}
    org_ids = authz.org_ids_for(db, user)
    if not org_ids:
        return {}
    return {
        int(row.id): row
        for row in db.execute(
            select(OrgResource).where(
                OrgResource.id.in_(sorted(ids)),
                OrgResource.org_id.in_(org_ids),
                OrgResource.allow_student_ai == 1,
                OrgResource.archived == 0,
            )
        ).scalars()
    }


def _accessible_resource(db: Session, user: User, resource_id: int) -> OrgResource | None:
    """单条版本，复用 :func:`_accessible_resources` 的可见性条件。"""
    return _accessible_resources(db, user, [int(resource_id)]).get(int(resource_id))


def _upsert_ref(db: Session, owner_id: int, resource_id: int) -> LibraryRef:
    """按 ``(owner_id, resource_id)`` 幂等写入：已存在只刷新 ``last_used_at``。"""
    ref = db.execute(
        select(LibraryRef).where(
            LibraryRef.owner_id == int(owner_id),
            LibraryRef.resource_id == int(resource_id),
        )
    ).scalars().first()
    now = _now_local()
    if ref is None:
        ref = LibraryRef(
            owner_id=int(owner_id),
            resource_id=int(resource_id),
            added_at=now,
            last_used_at=now,
        )
        db.add(ref)
    else:
        ref.last_used_at = now
    return ref


def list_refs(db: Session, user: User) -> tuple[list[LibraryRefOut], int]:
    """返回当前用户仍可访问的引用（最近使用在前）与被撤回条数。"""
    refs = list(
        db.execute(
            select(LibraryRef)
            .where(LibraryRef.owner_id == int(user.id))
            .order_by(LibraryRef.last_used_at.desc(), LibraryRef.id.desc())
        ).scalars()
    )
    if not refs:
        return [], 0

    org_ids = authz.org_ids_for(db, user)
    if not org_ids:
        return [], len(refs)

    resources = _accessible_resources(db, user, [int(ref.resource_id) for ref in refs])
    items = [
        to_out(ref, resources[int(ref.resource_id)])
        for ref in refs
        if int(ref.resource_id) in resources
    ]
    return items, len(refs) - len(items)


def save_ref(db: Session, user: User, resource_id: int) -> tuple[LibraryRef, OrgResource]:
    """前端「保存到 Library」：不可访问统一 ``4040``；upsert 后由调用方提交。"""
    resource = _accessible_resource(db, user, int(resource_id))
    if resource is None:
        raise ApiError(ERR_NOT_FOUND, "资料不存在", 404)
    ref = _upsert_ref(db, int(user.id), int(resource.id))
    return ref, resource


def record_citations(db: Session, user: User, resource_ids: Iterable[int] | None) -> int:
    """AI 回答后自动收藏引用；过滤不可访问项，任何异常只记日志、不向上抛。"""
    try:
        wanted = {int(item) for item in (resource_ids or [])}
    except (TypeError, ValueError):
        logger.warning("忽略非法的 AI 引用资源 id：%r", resource_ids)
        return 0
    if not wanted:
        return 0

    try:
        stored = 0
        for resource_id in sorted(wanted):
            if _accessible_resource(db, user, resource_id) is None:
                continue
            _upsert_ref(db, int(user.id), resource_id)
            stored += 1
        db.commit()
        return stored
    except Exception:  # noqa: BLE001 - 引用写入失败不得中断 AI 回答
        db.rollback()
        logger.exception("记录 AI 资料引用失败（user_id=%s）", getattr(user, "id", None))
        return 0


def has_active_ref(db: Session, user: User, resource_id: int) -> bool:
    """当前用户对该资料是否持有仍有效的引用。

    「有效」= 引用存在 且 资料当前仍可见（开关开启、未归档、用户仍在资料所属组织）；
    与 ``list_refs`` 共用 :func:`_accessible_resources`，避免列表已计撤回但仍可下载。
    """
    ref_exists = db.execute(
        select(LibraryRef.id).where(
            LibraryRef.owner_id == int(user.id),
            LibraryRef.resource_id == int(resource_id),
        )
    ).first()
    if ref_exists is None:
        return False
    return int(resource_id) in _accessible_resources(db, user, [int(resource_id)])


__all__ = [
    "has_active_ref",
    "list_refs",
    "record_citations",
    "save_ref",
    "to_out",
]