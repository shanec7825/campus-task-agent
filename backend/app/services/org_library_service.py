"""组织资料库服务（契约 `C-ORG-LIBRARY@1`）。

* 上传 / 列表 / 改开关 / 归档与下载权限都在本模块判定，路由只做参数绑定；
* 文件校验通过后才落盘，`file` 与 `url` 二选一，非法输入统一 ``4001``；
* 正文解析复用 :mod:`app.services.document_service` 的纯函数，失败只把
  ``text_status`` 置为 ``failed``，不阻断上传；
* 检索 :func:`search_allowed` 在 SQL 层过滤组织范围 / 开关 / 归档 / 解析状态，
  关闭开关后下一次调用立即不再命中（无应用层缓存）。
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import OrgResource, Organization, User
from app.schemas import (
    OrgResourceCreateIn,
    OrgResourceFileIn,
    OrgResourceOut,
    OrgResourcePatchIn,
)
from app.services import authz, document_service, kb_service

logger = logging.getLogger(__name__)

ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040

MANAGER_ROLES: tuple[str, ...] = ("admin", "collaborator")

MAX_FILE_BYTES = 20 * 1024 * 1024
# base64 字符串绝对上限：20MB 原始字节按 4/3 膨胀后再留 4 字节对齐余量
MAX_BASE64_CHARS = MAX_FILE_BYTES * 4 // 3 + 4
MAX_SNIPPET_CHARS = 200
DEFAULT_SEARCH_LIMIT = 5
MAX_SEARCH_LIMIT = 20
# 检索资源上限：候选资料数、单份资料切分字符数、段落数与单段长度
MAX_SEARCH_CANDIDATES = 50
MAX_SEARCH_TEXT_CHARS = 20_000
MAX_SEARCH_PARAGRAPHS = 20
MAX_PARAGRAPH_CHARS = 2_000
# 标题命中加权：标题是整份资料的概括，命中比正文段落更可信
TITLE_HIT_WEIGHT = 2

_DEFAULT_UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "org"
_ALLOWED_LINK_SCHEMES = frozenset({"http", "https"})
_PARAGRAPH_SPLIT = re.compile(r"\n+")
_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def upload_root() -> Path:
    """文件落盘根目录；每次调用读取 ``ORG_LIBRARY_UPLOAD_ROOT``，测试可动态隔离。"""
    raw = os.getenv("ORG_LIBRARY_UPLOAD_ROOT", "").strip()
    return Path(raw) if raw else _DEFAULT_UPLOAD_ROOT


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_out(row: OrgResource) -> OrgResourceOut:
    """公开序列化入口：路由与测试共用同一份字段映射。"""
    return OrgResourceOut.model_validate(row)


def require_manager(db: Session, user: User, org_id: int) -> None:
    """组织不存在 ``4040``；非 admin/collaborator（含非成员）``4030``。"""
    if db.get(Organization, int(org_id)) is None:
        raise ApiError(ERR_NOT_FOUND, "组织不存在", 404)
    if authz.org_role(db, user, int(org_id)) not in MANAGER_ROLES:
        raise ApiError(ERR_FORBIDDEN, "无权管理该组织资料", 403)



def _normalize_title(value: str | None) -> str:
    title = (value or "").strip()
    if not title:
        raise ApiError(ERR_INVALID_PARAM, "标题不能为空")
    if len(title) > 200:
        raise ApiError(ERR_INVALID_PARAM, "标题长度不能超过 200 个字符")
    return title


def _normalize_summary(value: str | None) -> str | None:
    if value is None:
        return None
    summary = value.strip()
    if not summary:
        return None
    if len(summary) > 2000:
        raise ApiError(ERR_INVALID_PARAM, "简介长度不能超过 2000 个字符")
    return summary


def _normalize_url(value: str) -> str:
    url = value.strip()
    if len(url) > 1000:
        raise ApiError(ERR_INVALID_PARAM, "链接长度不能超过 1000 个字符")
    if any(char in url for char in ("\r", "\n", "\t")):
        raise ApiError(ERR_INVALID_PARAM, "链接不能包含换行或制表符")
    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_LINK_SCHEMES or not parts.netloc:
        raise ApiError(ERR_INVALID_PARAM, "链接必须是 http/https 开头且包含主机名")
    return url


def _decode_file(file: OrgResourceFileIn) -> tuple[bytes, str, str]:
    """校验扩展名 / 大小 / base64 长度并解码；返回 ``(payload, 原始名, 扩展名)``。

    base64 在解码前先按声明大小反推字符串上限（``size * 4 // 3 + 4``），超限直接
    ``4001``，避免为超大字符串分配解码后的字节。
    """
    original = PurePosixPath((file.name or "").replace("\\", "/")).name.strip()
    ext = PurePosixPath(original).suffix.lower()
    if not original or ext not in document_service.PARSEABLE_EXTS:
        raise ApiError(ERR_INVALID_PARAM, "仅支持 PDF/DOCX/TXT/MD")
    if file.size > MAX_FILE_BYTES:
        raise ApiError(ERR_INVALID_PARAM, "文件不能超过 20MB")
    encoded = file.data_base64
    if len(encoded) > MAX_BASE64_CHARS:
        raise ApiError(ERR_INVALID_PARAM, "文件内容超出大小上限")
    compact = "".join(encoded.split())
    if len(compact) > int(file.size) * 4 // 3 + 4:
        raise ApiError(ERR_INVALID_PARAM, "文件内容与声明大小不一致")
    try:
        payload = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError(ERR_INVALID_PARAM, "文件内容不是合法的 base64") from exc
    if len(payload) != int(file.size):
        raise ApiError(ERR_INVALID_PARAM, "文件大小与实际内容不一致")
    return payload, original[:255], ext


def _save_file(org_id: int, ext: str, payload: bytes) -> str:
    """落盘并返回相对 ``ORG_LIBRARY_UPLOAD_ROOT`` 的路径。"""
    relative = f"{int(org_id)}/{uuid.uuid4().hex}{ext}"
    target = upload_root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return relative


def create(db: Session, user: User, payload: OrgResourceCreateIn) -> OrgResource:
    """校验 → 落盘 → 解析 → 插入，单事务提交；失败时回滚并删除已落盘文件。"""
    require_manager(db, user, payload.org_id)
    title = _normalize_title(payload.title)
    summary = _normalize_summary(payload.summary)
    url = (payload.url or "").strip()

    if payload.file is not None and url:
        raise ApiError(ERR_INVALID_PARAM, "文件与链接只能二选一")
    if payload.file is None and not url:
        raise ApiError(ERR_INVALID_PARAM, "必须提供文件或链接")

    stored: str | None = None
    text_status = "pending"
    content: str | None = None
    fields: dict[str, object] = {
        "org_id": int(payload.org_id),
        "title": title,
        "summary": summary,
        "resource_type": "file" if payload.file is not None else "link",
        "url": None,
        "created_by": int(user.id),
        "allow_student_ai": 0,
        "archived": 0,
    }

    if payload.file is not None:
        data, original, ext = _decode_file(payload.file)
        stored = _save_file(int(payload.org_id), ext, data)
        text_status, text = document_service.extract_text(original, data)
        content = text or None
        fields.update(
            {
                "file_name": original,
                "file_mime": _MIME_BY_EXT.get(ext, "application/octet-stream"),
                "file_size": len(data),
                "file_path": stored,
            }
        )
    else:
        fields["url"] = _normalize_url(url)

    fields.update(
        {
            "content_text": content,
            "search_text": content,
            "text_status": text_status,
        }
    )

    row = OrgResource(**fields)
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        if stored is not None:
            (upload_root() / stored).unlink(missing_ok=True)
        raise
    db.refresh(row)
    return row


def list(
    db: Session, user: User, org_id: int, *, include_archived: bool = False
) -> list[OrgResource]:
    """组织资料列表（新的在前）；默认不返回已归档条目。"""
    require_manager(db, user, org_id)
    condition = [OrgResource.org_id == int(org_id)]
    if not include_archived:
        condition.append(OrgResource.archived == 0)
    rows = db.execute(
        select(OrgResource)
        .where(*condition)
        .order_by(OrgResource.created_at.desc(), OrgResource.id.desc())
    ).scalars()
    # 注意：本模块公开函数名 ``list`` 遮蔽了内置 ``list``，因此不能在此调用 ``list(rows)``。
    return rows.all()


def get(db: Session, resource_id: int) -> OrgResource:
    row = db.get(OrgResource, int(resource_id))
    if row is None:
        raise ApiError(ERR_NOT_FOUND, "资料不存在", 404)
    return row


def update_flags(
    db: Session, user: User, resource_id: int, payload: OrgResourcePatchIn
) -> OrgResource:
    """PATCH 局部更新：只改传入字段；无字段 ``4001``；权限按资料归属组织判定。"""
    row = get(db, resource_id)
    require_manager(db, user, row.org_id)

    fields = payload.model_fields_set
    if not fields:
        raise ApiError(ERR_INVALID_PARAM, "没有需要更新的字段")

    if "title" in fields:
        row.title = _normalize_title(payload.title)
    if "summary" in fields:
        row.summary = _normalize_summary(payload.summary)
    if "allow_student_ai" in fields:
        if payload.allow_student_ai is None:
            raise ApiError(ERR_INVALID_PARAM, "allow_student_ai 必须是布尔值")
        row.allow_student_ai = 1 if payload.allow_student_ai else 0
    if "archived" in fields:
        if payload.archived is None:
            raise ApiError(ERR_INVALID_PARAM, "archived 必须是布尔值")
        row.archived = 1 if payload.archived else 0

    row.updated_at = _now_local()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return row


def _paragraphs(text: str | None) -> list[str]:
    # 单段先截到 MAX_PARAGRAPH_CHARS：超长单行不能让分词与打分无界增长
    return [
        part.strip()[:MAX_PARAGRAPH_CHARS]
        for part in _PARAGRAPH_SPLIT.split(text or "")
        if part.strip()
    ]


def search_allowed(
    db: Session, user: User, query: str, limit: int = DEFAULT_SEARCH_LIMIT
) -> list[dict[str, object]]:
    """按组织与开关过滤的章节检索（`C-ORG-LIBRARY@1`，供 S4 的 AI 引用）。

    返回 ``[{resource_id, title, snippet, score, org_id}]``，按分数降序；
    分数 = 命中段落 token 交集数 + ``TITLE_HIT_WEIGHT`` × 标题 token 交集数。
    """
    q_tokens = kb_service.tokenize(query)
    if not q_tokens:
        return []
    org_ids = authz.org_ids_for(db, user)
    if not org_ids:
        return []

    q_set = set(q_tokens)
    rows = db.execute(
        select(OrgResource)
        .where(
            OrgResource.org_id.in_(org_ids),
            OrgResource.allow_student_ai == 1,
            OrgResource.archived == 0,
            OrgResource.text_status == "ready",
        )
        .order_by(OrgResource.updated_at.desc(), OrgResource.id.desc())
        .limit(MAX_SEARCH_CANDIDATES)
    ).scalars()

    scored: list[dict[str, object]] = []
    for row in rows:
        source = (row.search_text or row.content_text or "")[:MAX_SEARCH_TEXT_CHARS]
        paragraphs = _paragraphs(source)[:MAX_SEARCH_PARAGRAPHS]
        best_hits = 0
        best_snippet = ""
        for paragraph in paragraphs:
            hits = len(q_set & set(kb_service.tokenize(paragraph)))
            if hits > best_hits:
                best_hits = hits
                best_snippet = paragraph[:MAX_SNIPPET_CHARS]

        title_hits = len(q_set & set(kb_service.tokenize(row.title)))
        score = best_hits + TITLE_HIT_WEIGHT * title_hits
        if score <= 0:
            continue
        snippet = best_snippet or (
            paragraphs[0][:MAX_SNIPPET_CHARS] if paragraphs else (row.title or "")[:MAX_SNIPPET_CHARS]
        )
        scored.append(
            {
                "resource_id": int(row.id),
                "title": row.title,
                "snippet": snippet,
                "score": score,
                "org_id": int(row.org_id),
            }
        )

    scored.sort(key=lambda item: (-int(item["score"]), int(item["resource_id"])))
    capped = max(1, min(int(limit), MAX_SEARCH_LIMIT))
    return scored[:capped]


__all__ = [
    "MANAGER_ROLES",
    "MAX_FILE_BYTES",
    "MAX_SEARCH_CANDIDATES",
    "create",
    "get",
    "list",
    "require_manager",
    "search_allowed",
    "to_out",
    "update_flags",
    "upload_root",
]