#!/usr/bin/env python
"""S4 引用式收藏与下载可见性测试（契约 `C-LIB-REF@1`）。

覆盖范围（真实 HTTP + 真实 SQLite）：

1. ``library_refs`` 列与具名唯一索引；
2. ``POST /api/library/refs`` upsert 幂等（同一 ``(owner, resource)`` 只有一行）；
3. ``GET /api/library/refs`` 只返回仍可访问的引用，并给出 ``revoked_count``；
4. 跨组织 / 未开放 / 已归档 / 不存在的资料 → ``4040``；
5. 学生凭有效引用下载；关闭开关、归档、解除引用后 → ``4040``，重新开启后恢复；
6. ``record_citations`` 过滤不可访问项且绝不抛异常。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH``、``ORG_LIBRARY_UPLOAD_ROOT``、
``MAAS_MOCK=1``、``MAAS_API_KEY=''``、``RUN_SCHEDULER=0``；不触碰 ``backend/campus.db``
与 ``backend/uploads``。
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-s4-library-refs-"))
_TEST_DB_PATH = _TMP_DIR / "library_refs.db"
_UPLOAD_ROOT = _TMP_DIR / "org-uploads"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["ORG_LIBRARY_UPLOAD_ROOT"] = str(_UPLOAD_ROOT)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import LibraryRef, OrgMember, OrgResource, Organization, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import library_ref_service  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

PASSWORD = "TestPass123!"
ERR_NOT_FOUND = 4040
FILE_BODY = b"s4 library ref download payload"


@dataclass
class _Ctx:
    client: TestClient
    admin: dict[str, str]
    students: list[dict[str, str]]
    outsider: dict[str, str]
    other_admin: dict[str, str]
    org_id: int
    other_org_id: int


# --------------------------------------------------------------------------- #
# HTTP / 数据辅助
# --------------------------------------------------------------------------- #
def _payload(
    client: TestClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
) -> tuple[int, dict]:
    response = client.request(method, path, json=body, headers=headers or {})
    try:
        parsed = response.json()
    except ValueError:  # pragma: no cover - 非 JSON 说明发生未捕获异常
        raise AssertionError(f"{method} {path}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert isinstance(parsed, dict), f"{method} {path}：响应体不是对象"
    return response.status_code, parsed


def _ok(
    client: TestClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    label: str = "",
) -> dict:
    status, parsed = _payload(client, method, path, headers=headers, body=body)
    assert status == 200, f"{label}：期望 HTTP 200，实际 HTTP {status}（{parsed.get('msg')}）"
    assert parsed.get("code") == 0, (
        f"{label}：期望 code=0，实际 code={parsed.get('code')}（msg={parsed.get('msg')}）"
    )
    data = parsed.get("data")
    assert isinstance(data, dict), f"{label}：data 不是对象（{type(data).__name__}）"
    return data


def _err(
    client: TestClient,
    method: str,
    path: str,
    *,
    code: int,
    status: int,
    headers: dict[str, str] | None = None,
    body: Any = None,
    label: str = "",
) -> dict:
    actual_status, parsed = _payload(client, method, path, headers=headers, body=body)
    assert parsed.get("code") == code, (
        f"{label}：期望 code={code}，实际 code={parsed.get('code')}（msg={parsed.get('msg')}）"
    )
    assert actual_status == status, f"{label}：期望 HTTP {status}，实际 HTTP {actual_status}"
    return parsed


def _session_headers(response) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in response.headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        if name.strip() in {SESSION_COOKIE, CSRF_COOKIE}:
            values[name.strip()] = rest.split(";", 1)[0].strip()
    session = values.get(SESSION_COOKIE)
    csrf = values.get(CSRF_COOKIE)
    assert session and csrf, "登录响应缺少会话 Cookie"
    return {
        "Cookie": f"{SESSION_COOKIE}={session}; {CSRF_COOKIE}={csrf}",
        CSRF_HEADER: csrf,
    }


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    parsed = response.json()
    assert response.status_code == 200 and parsed.get("code") == 0, (
        f"登录 {username} 失败：HTTP {response.status_code} / code={parsed.get('code')}"
    )
    headers = _session_headers(response)
    client.cookies.clear()
    return headers


def _ensure_user(username: str, display_name: str) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(username=username, display_name=display_name, role="student", credits=0)
            db.add(user)
        user.password_hash = hash_password(PASSWORD)
        user.status = "active"
        db.commit()
        db.refresh(user)
        return int(user.id)


def _ensure_org(name: str, slug: str, roles: dict[int, str]) -> int:
    with SessionLocal() as db:
        org = db.query(Organization).filter(Organization.slug == slug).first()
        if org is None:
            org = Organization(name=name, slug=slug, status="active")
            db.add(org)
            db.flush()
        existing = {
            int(row.user_id): row
            for row in db.query(OrgMember).filter(OrgMember.org_id == int(org.id)).all()
        }
        for user_id, role in roles.items():
            row = existing.get(int(user_id))
            if row is None:
                db.add(
                    OrgMember(org_id=int(org.id), user_id=int(user_id), role=role, status="active")
                )
            else:
                row.role = role
                row.status = "active"
        db.commit()
        db.refresh(org)
        return int(org.id)


def _upload(
    ctx: _Ctx, headers: dict[str, str], title: str, *, org_id: int | None = None
) -> dict:
    body = {
        "org_id": ctx.org_id if org_id is None else org_id,
        "title": title,
        "summary": f"{title} 的摘要",
        "file": {
            "name": "ref-material.txt",
            "mime": "text/plain",
            "size": len(FILE_BODY),
            "data_base64": base64.b64encode(FILE_BODY).decode("ascii"),
        },
    }
    return _ok(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=headers,
        body=body,
        label=f"上传「{title}」",
    )


def _patch(ctx: _Ctx, resource_id: int, body: dict, *, headers: dict[str, str] | None = None) -> dict:
    return _ok(
        ctx.client,
        "PATCH",
        f"/api/org-resources/{resource_id}",
        headers=ctx.admin if headers is None else headers,
        body=body,
        label=f"PATCH 资料 {resource_id}",
    )


def _open(ctx: _Ctx, title: str) -> dict:
    """上传并开启学生 AI 检索，返回资料。"""
    created = _upload(ctx, ctx.admin, title)
    _patch(ctx, created["id"], {"allow_student_ai": True})
    return created


def _save_ref(ctx: _Ctx, headers: dict[str, str], resource_id: int) -> dict:
    return _ok(
        ctx.client,
        "POST",
        "/api/library/refs",
        headers=headers,
        body={"resource_id": resource_id},
        label=f"保存引用 {resource_id}",
    )


def _list_refs(ctx: _Ctx, headers: dict[str, str]) -> dict:
    return _ok(
        ctx.client,
        "GET",
        "/api/library/refs",
        headers=headers,
        label="引用列表",
    )


def _ref_rows(username: str) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one()
        return db.query(LibraryRef).filter(LibraryRef.owner_id == int(user.id)).count()


def _set_membership(ctx: _Ctx, username: str, *, active: bool) -> None:
    """把学生移出 / 重新加入测试组织（``authz.org_ids_for`` 只认 active 成员行）。"""
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one()
        query = db.query(OrgMember).filter(
            OrgMember.org_id == int(ctx.org_id), OrgMember.user_id == int(user.id)
        )
        if not active:
            query.delete()
        elif query.first() is None:
            db.add(
                OrgMember(
                    org_id=int(ctx.org_id),
                    user_id=int(user.id),
                    role="member",
                    status="active",
                )
            )
        db.commit()


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        admin_id = _ensure_user("s4_ref_admin", "S4 Admin")
        other_admin_id = _ensure_user("s4_ref_other_admin", "S4 Other Admin")
        student_names = [
            "s4_ref_stu1",
            "s4_ref_stu2",
            "s4_ref_stu3",
            "s4_ref_stu4",
            "s4_ref_stu5",
            "s4_ref_stu6",
        ]
        student_ids = [_ensure_user(name, name) for name in student_names]
        outsider_id = _ensure_user("s4_ref_outsider", "S4 Outsider")

        org_id = _ensure_org(
            "S4 引用组织", "s4-ref-org", roles={admin_id: "admin", **{sid: "member" for sid in student_ids}}
        )
        other_org_id = _ensure_org(
            "S4 其它组织",
            "s4-ref-other-org",
            roles={other_admin_id: "admin", outsider_id: "member"},
        )

        yield _Ctx(
            client=client,
            admin=_login(client, "s4_ref_admin"),
            students=[_login(client, name) for name in student_names],
            outsider=_login(client, "s4_ref_outsider"),
            other_admin=_login(client, "s4_ref_other_admin"),
            org_id=org_id,
            other_org_id=other_org_id,
        )


# --------------------------------------------------------------------------- #
# 表结构
# --------------------------------------------------------------------------- #
def test_library_refs_table_shape() -> None:
    init_db()
    with engine.connect() as conn:
        columns = {
            row[1]: row for row in conn.exec_driver_sql("PRAGMA table_info(library_refs)").fetchall()
        }
        indexes = {
            row[1]: row
            for row in conn.exec_driver_sql("PRAGMA index_list(library_refs)").fetchall()
        }

    assert {"id", "owner_id", "resource_id", "added_at", "last_used_at"} <= set(columns)
    for column in ("owner_id", "resource_id", "added_at", "last_used_at"):
        assert columns[column][3] == 1, f"{column} 必须是 NOT NULL"
    assert "uq_library_refs_owner_resource" in indexes, f"缺少唯一索引：{indexes}"
    assert indexes["uq_library_refs_owner_resource"][2] == 1, "uq_library_refs_owner_resource 必须唯一"
    assert "ix_library_refs_owner_id" in indexes, f"缺少 owner 索引：{indexes}"


# --------------------------------------------------------------------------- #
# 引用写入与列表
# --------------------------------------------------------------------------- #
def test_save_ref_upsert_is_idempotent(ctx: _Ctx) -> None:
    created = _open(ctx, "S4 幂等引用资料")
    first = _save_ref(ctx, ctx.students[0], created["id"])

    assert first["resource_id"] == created["id"]
    assert first["title"] == "S4 幂等引用资料"
    assert first["summary"] == "S4 幂等引用资料 的摘要"
    assert first["resource_type"] == "file"
    assert first["file_name"] == "ref-material.txt"
    assert first["file_size"] == len(FILE_BODY)
    assert first["url"] is None
    assert first["org_id"] == ctx.org_id
    assert first["added_at"] and first["last_used_at"]
    assert "owner_id" not in first, "响应不得返回 owner_id"

    second = _save_ref(ctx, ctx.students[0], created["id"])
    assert second["added_at"] == first["added_at"], "重复引用不得改写首次收藏时间"
    assert second["last_used_at"] >= first["last_used_at"]
    assert _ref_rows("s4_ref_stu1") == 1, "同一资料重复引用必须只有一行"

    listed = _list_refs(ctx, ctx.students[0])
    assert [item["resource_id"] for item in listed["items"]] == [created["id"]]
    assert listed["revoked_count"] == 0


def test_list_refs_only_visible_and_counts_revoked(ctx: _Ctx) -> None:
    headers = ctx.students[1]
    visible = _open(ctx, "S4 可见引用")
    closed = _open(ctx, "S4 被关闭引用")
    archived = _open(ctx, "S4 被归档引用")
    for item in (visible, closed, archived):
        _save_ref(ctx, headers, item["id"])

    _patch(ctx, closed["id"], {"allow_student_ai": False})
    _patch(ctx, archived["id"], {"archived": True})

    listed = _list_refs(ctx, headers)
    assert [item["resource_id"] for item in listed["items"]] == [visible["id"]]
    assert listed["revoked_count"] == 2, "关闭开关与归档各计一条撤回"
    titles = {item["title"] for item in listed["items"]}
    assert titles == {"S4 可见引用"}, "不得返回已撤回引用的标题"


def test_save_ref_rejects_invisible(ctx: _Ctx) -> None:
    headers = ctx.students[2]

    foreign = _upload(ctx, ctx.other_admin, "S4 外组织资料", org_id=ctx.other_org_id)
    _patch(ctx, foreign["id"], {"allow_student_ai": True}, headers=ctx.other_admin)

    closed = _upload(ctx, ctx.admin, "S4 未开放资料")
    archived = _open(ctx, "S4 已归档资料")
    _patch(ctx, archived["id"], {"archived": True})

    for resource_id, label in (
        (foreign["id"], "跨组织资料"),
        (closed["id"], "未开放资料"),
        (archived["id"], "已归档资料"),
        (99999999, "不存在的资料"),
    ):
        _err(
            ctx.client,
            "POST",
            "/api/library/refs",
            headers=headers,
            body={"resource_id": resource_id},
            code=ERR_NOT_FOUND,
            status=404,
            label=label,
        )
    assert _ref_rows("s4_ref_stu3") == 0, "不可访问资料不得落库引用"


# --------------------------------------------------------------------------- #
# 下载可见性
# --------------------------------------------------------------------------- #
def test_download_by_ref_respects_visibility(ctx: _Ctx) -> None:
    headers = ctx.students[3]
    created = _open(ctx, "S4 引用下载资料")
    _save_ref(ctx, headers, created["id"])
    path = f"/api/org-resources/{created['id']}/download"

    response = ctx.client.get(path, headers=headers)
    assert response.status_code == 200, f"持有引用应可下载：HTTP {response.status_code}"
    assert response.content == FILE_BODY

    _patch(ctx, created["id"], {"allow_student_ai": False})
    _err(
        ctx.client,
        "GET",
        path,
        headers=headers,
        code=ERR_NOT_FOUND,
        status=404,
        label="关闭开关后下载",
    )

    _patch(ctx, created["id"], {"allow_student_ai": True})
    assert ctx.client.get(path, headers=headers).status_code == 200, "重新开启后应恢复下载"

    _patch(ctx, created["id"], {"archived": True})
    _err(
        ctx.client,
        "GET",
        path,
        headers=headers,
        code=ERR_NOT_FOUND,
        status=404,
        label="归档后下载",
    )

    _patch(ctx, created["id"], {"archived": False})
    assert ctx.client.get(path, headers=headers).status_code == 200, "恢复归档后应恢复下载"

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "s4_ref_stu4").one()
        db.query(LibraryRef).filter(
            LibraryRef.owner_id == int(user.id), LibraryRef.resource_id == int(created["id"])
        ).delete()
        db.commit()
    _err(
        ctx.client,
        "GET",
        path,
        headers=headers,
        code=ERR_NOT_FOUND,
        status=404,
        label="解除引用后下载",
    )

    _err(
        ctx.client,
        "GET",
        path,
        headers=ctx.outsider,
        code=ERR_NOT_FOUND,
        status=404,
        label="跨组织无引用下载",
    )


def test_ref_access_follows_org_membership(ctx: _Ctx) -> None:
    headers = ctx.students[5]
    created = _open(ctx, "S4 组织移出引用资料")
    _save_ref(ctx, headers, created["id"])
    path = f"/api/org-resources/{created['id']}/download"

    assert ctx.client.get(path, headers=headers).status_code == 200, "在组织中应可凭引用下载"
    listed = _list_refs(ctx, headers)
    assert [item["resource_id"] for item in listed["items"]] == [created["id"]]
    assert listed["revoked_count"] == 0

    _set_membership(ctx, "s4_ref_stu6", active=False)
    listed = _list_refs(ctx, headers)
    assert listed["items"] == [], "移出组织后引用必须计入撤回而不是继续展示"
    assert listed["revoked_count"] == 1
    _err(
        ctx.client,
        "GET",
        path,
        headers=headers,
        code=ERR_NOT_FOUND,
        status=404,
        label="移出组织后下载",
    )
    _err(
        ctx.client,
        "POST",
        "/api/library/refs",
        headers=headers,
        body={"resource_id": created["id"]},
        code=ERR_NOT_FOUND,
        status=404,
        label="移出组织后保存引用",
    )
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "s4_ref_stu6").one()
        assert library_ref_service.record_citations(db, user, [created["id"]]) == 0
        assert _ref_rows("s4_ref_stu6") == 1, "record_citations 不得绕过组织可见性"

    _set_membership(ctx, "s4_ref_stu6", active=True)
    assert ctx.client.get(path, headers=headers).status_code == 200, "重新加入组织后应恢复下载"
    listed = _list_refs(ctx, headers)
    assert [item["resource_id"] for item in listed["items"]] == [created["id"]]
    assert listed["revoked_count"] == 0


# --------------------------------------------------------------------------- #
# AI 引用写入
# --------------------------------------------------------------------------- #
def test_record_citations_filters_and_never_raises(ctx: _Ctx) -> None:
    opened = _open(ctx, "S4 AI 引用资料")
    closed = _upload(ctx, ctx.admin, "S4 AI 未开放资料")

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "s4_ref_stu5").one()
        stored = library_ref_service.record_citations(
            db, user, [opened["id"], closed["id"], 99999999]
        )
        assert stored == 1, "只应记录可访问资料"

        rows = db.query(LibraryRef).filter(LibraryRef.owner_id == int(user.id)).all()
        assert [int(row.resource_id) for row in rows] == [opened["id"]]

        again = library_ref_service.record_citations(db, user, [opened["id"], opened["id"]])
        assert again == 1 and _ref_rows("s4_ref_stu5") == 1, "重复引用必须幂等"

        assert library_ref_service.record_citations(db, user, ["not-an-int"]) == 0
        assert library_ref_service.record_citations(db, user, None) == 0