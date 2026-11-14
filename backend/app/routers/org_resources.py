"""组织资料库路由（契约 `C-ORG-LIBRARY@1`）。

* ``POST /api/org-resources``：上传文件或登记链接（解析失败仍保存）；
* ``GET /api/org-resources``：按组织列出资料，默认隐藏已归档；
* ``PATCH /api/org-resources/{id}``：局部更新标题 / 简介 / AI 检索开关 / 归档；
* ``POST /api/org-resources/from-submission``：把已验收成果归档为组织资料（`C-ARCHIVE@1`）；
* ``GET /api/org-resources/{id}/download``：下载原文件（组织管理者，或持有有效引用的学生）。

权限与校验全部在 ``services.org_library_service`` 内完成；router 级 CSRF 双提交校验。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf
from app.errors import ApiError, ok
from app.models import User
from app.schemas import ArchiveSubmissionIn, OrgResourceCreateIn, OrgResourcePatchIn
from app.services import library_ref_service, org_library_service

router = APIRouter(
    prefix="/api/org-resources", tags=["org-resources"], dependencies=[Depends(require_csrf)]
)

ERR_INVALID_PARAM = 4001


@router.post("")
def create_resource(
    payload: OrgResourceCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """上传组织资料：文件 / 链接二选一，返回不含正文的条目。"""
    row = org_library_service.create(db, current_user, payload)
    return ok(org_library_service.to_out(row).model_dump())


@router.post("/from-submission")
def archive_from_submission(
    payload: ArchiveSubmissionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """把已验收成果归档为组织资料（`C-ARCHIVE@1`），默认关闭学生 AI 检索。"""
    row = org_library_service.archive_submission(
        db, current_user, payload.submission_id, payload.org_id, payload.title
    )
    return ok(org_library_service.to_out(row).model_dump())


@router.get("")
def list_resources(
    org_id: int = Query(...),
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """组织资料列表（`created_at DESC`），默认不返回已归档条目。"""
    rows = org_library_service.list(
        db, current_user, org_id, include_archived=include_archived
    )
    return ok({"items": [org_library_service.to_out(row).model_dump() for row in rows]})


@router.patch("/{resource_id}")
def update_resource(
    resource_id: int,
    payload: OrgResourcePatchIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """局部更新；未传字段保持不变，无字段 4001。"""
    row = org_library_service.update_flags(db, current_user, resource_id, payload)
    return ok(org_library_service.to_out(row).model_dump())


@router.get("/{resource_id}/download")
def download_resource(
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """下载文件类资料：组织管理者，或持有有效引用的学生（`C-LIB-REF@1`）。

    无组织管理权限且无有效引用时统一 4040，不区分「不存在」与「无权限」，
    避免用状态码探测资料是否存在。
    """
    row = org_library_service.get(db, resource_id)
    if not library_ref_service.has_active_ref(db, current_user, row.id):
        try:
            org_library_service.require_manager(db, current_user, row.org_id)
        except ApiError as exc:
            raise ApiError(4040, "资料不存在", 404) from exc
    if row.resource_type != "file" or not row.file_path:
        raise ApiError(ERR_INVALID_PARAM, "该资料没有可下载的文件")
    path = org_library_service.upload_root() / row.file_path
    if not path.is_file():
        raise ApiError(4040, "文件不存在", 404)
    return FileResponse(
        path,
        media_type=row.file_mime or "application/octet-stream",
        filename=row.file_name or path.name,
    )


__all__ = ["router"]