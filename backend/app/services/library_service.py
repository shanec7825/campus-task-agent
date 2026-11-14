"""Library 私有参考链接服务（契约 `C-LIBRARY@1`，设计 §9.2）。

* ``owner_id`` 只从当前会话 ``current_user`` 取，不接受客户端传入；
* 列表 / 读取 / 更新一律按 owner 过滤，非本人与不存在返回同一 ``4040``，避免猜 ID；
* ``url`` 只接受 ``http`` / ``https`` 且必须带主机名，危险 scheme 统一 ``4001``；
* 不删除、不公开共享、不请求用户外链。
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import LibraryLink, User
from app.schemas import LibraryLinkCreateIn, LibraryLinkOut, LibraryLinkUpdateIn

ERR_INVALID_PARAM = 4001
ERR_NOT_FOUND = 4040

MAX_TITLE = 200
MAX_URL = 1000
MAX_NOTE = 2000
MAX_LIMIT = 50
DEFAULT_LIMIT = 20

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_FORBIDDEN_URL_CHARS = ("\r", "\n", "\t")


def _now_local() -> str:

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_title(value: str | None) -> str:
    title = (value or "").strip()
    if not title:
        raise ApiError(ERR_INVALID_PARAM, "标题不能为空")
    if len(title) > MAX_TITLE:
        raise ApiError(ERR_INVALID_PARAM, f"标题长度不能超过 {MAX_TITLE} 个字符")
    return title


def _normalize_url(value: str | None) -> str:
    url = (value or "").strip()
    if not url:
        raise ApiError(ERR_INVALID_PARAM, "链接地址不能为空")
    if len(url) > MAX_URL:
        raise ApiError(ERR_INVALID_PARAM, f"链接地址长度不能超过 {MAX_URL} 个字符")
    if any(char in url for char in _FORBIDDEN_URL_CHARS):
        raise ApiError(ERR_INVALID_PARAM, "链接地址不能包含换行或制表符")
    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES or not parts.netloc:
        raise ApiError(ERR_INVALID_PARAM, "链接地址必须是 http/https 开头且包含主机名")
    return url


def _normalize_note(value: str | None) -> str | None:
    if value is None:
        return None
    note = value.strip()
    if not note:
        return None
    if len(note) > MAX_NOTE:
        raise ApiError(ERR_INVALID_PARAM, f"说明长度不能超过 {MAX_NOTE} 个字符")
    return note


def to_out(row: LibraryLink) -> LibraryLinkOut:
    """公开序列化入口：路由与测试复用同一份字段映射。"""
    return LibraryLinkOut.model_validate(row)


def list_links(
    db: Session, user: User, *, offset: int = 0, limit: int = DEFAULT_LIMIT
) -> tuple[list[LibraryLink], int]:
    """当前用户可见的个人链接（新的在前）与总数；只按 owner 过滤。"""
    query = db.query(LibraryLink).filter(LibraryLink.owner_id == int(user.id))
    total = query.count()
    rows = (
        query.order_by(LibraryLink.updated_at.desc(), LibraryLink.id.desc())
        .offset(int(offset))
        .limit(int(limit))
        .all()
    )
    return rows, total


def get_own_link(db: Session, user: User, link_id: int) -> LibraryLink:
    """按 owner 取链接；非本人或不存在一律 4040（不区分，避免枚举）。"""
    row = (
        db.query(LibraryLink)
        .filter(LibraryLink.id == int(link_id), LibraryLink.owner_id == int(user.id))
        .first()
    )
    if row is None:
        raise ApiError(ERR_NOT_FOUND, "链接不存在")
    return row


def create_link(db: Session, user: User, payload: LibraryLinkCreateIn) -> LibraryLink:
    """新建个人链接；所有者固定为当前会话用户。"""
    row = LibraryLink(
        owner_id=int(user.id),
        title=_normalize_title(payload.title),
        url=_normalize_url(payload.url),
        note=_normalize_note(payload.note),
        created_at=_now_local(),
        updated_at=_now_local(),
    )
    db.add(row)
    return row


def update_link(
    db: Session, user: User, link_id: int, payload: LibraryLinkUpdateIn
) -> LibraryLink:
    """更新本人的链接元数据；未提供的字段保持不变。"""
    row = get_own_link(db, user, link_id)
    provided = payload.model_dump(exclude_unset=True)
    if "title" in provided:
        row.title = _normalize_title(provided["title"])
    if "url" in provided:
        row.url = _normalize_url(provided["url"])
    if "note" in provided:
        row.note = _normalize_note(provided["note"])
    row.updated_at = _now_local()
    return row


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "create_link",
    "get_own_link",
    "list_links",
    "to_out",
    "update_link",
]