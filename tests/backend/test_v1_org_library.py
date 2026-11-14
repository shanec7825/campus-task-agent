#!/usr/bin/env python
"""S3 组织资料库接口与检索开关行为测试（契约 `C-ORG-LIBRARY@1`）。

覆盖范围（全部走真实 HTTP + 真实 SQLite）：

1. 上传 PDF / DOCX 后 ``text_status=ready``，正文落库；解析失败仍保存为 ``failed``；
2. 超过 20MB、非法扩展名、声明大小与 base64 实际长度不一致 → ``4001`` 且不落盘；
3. ``allow_student_ai`` / ``archived`` 默认关闭；开关开启后 ``search_allowed`` 命中，
   关闭或归档后立即不再命中（无缓存旁路），且只命中本人所属组织；
4. 非 admin/collaborator 调用管理接口 → ``4030``；组织不存在 → ``4040``；
5. 下载对同组织 admin/collaborator 开放，member / 外组织统一 4040 掩码拒绝，链接资料无下载文件 → ``4001``；
6. PATCH 只改传入字段，空 body → ``4001``。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH``、``ORG_LIBRARY_UPLOAD_ROOT``、
``MAAS_MOCK=1``、``MAAS_API_KEY=''``、``RUN_SCHEDULER=0``；不触碰 ``backend/campus.db``
与 ``backend/uploads``。
"""

from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-s3-org-library-"))
_TEST_DB_PATH = _TMP_DIR / "org_library.db"
_UPLOAD_ROOT = _TMP_DIR / "org-uploads"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["ORG_LIBRARY_UPLOAD_ROOT"] = str(_UPLOAD_ROOT)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import OrgMember, OrgResource, Organization, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import org_library_service  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

PASSWORD = "TestPass123!"
ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@dataclass
class _Ctx:
    client: TestClient
    alice: dict[str, str]
    bob: dict[str, str]
    carol: dict[str, str]
    dave: dict[str, str]
    org_id: int
    other_org_id: int


# --------------------------------------------------------------------------- #
# 最小 PDF / DOCX 生成（不引入额外依赖）
# --------------------------------------------------------------------------- #
def _pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 20 150 Td ({text}) Tj ET".encode("latin-1")
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)


def _docx_bytes(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


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
    ctx: _Ctx,
    headers: dict[str, str],
    title: str,
    *,
    name: str,
    data: bytes,
    mime: str = "application/pdf",
    size: int | None = None,
    org_id: int | None = None,
    label: str = "",
) -> dict:
    body = {
        "org_id": ctx.org_id if org_id is None else org_id,
        "title": title,
        "file": {
            "name": name,
            "mime": mime,
            "size": len(data) if size is None else size,
            "data_base64": base64.b64encode(data).decode("ascii"),
        },
    }
    return _ok(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=headers,
        body=body,
        label=label or f"上传「{title}」",
    )


def _patch(
    ctx: _Ctx, headers: dict[str, str], resource_id: int, body: dict, label: str = ""
) -> dict:
    return _ok(
        ctx.client,
        "PATCH",
        f"/api/org-resources/{resource_id}",
        headers=headers,
        body=body,
        label=label or f"PATCH 资料 {resource_id}",
    )


def _stored_files() -> list[Path]:
    if not _UPLOAD_ROOT.is_dir():
        return []
    return [path for path in _UPLOAD_ROOT.rglob("*") if path.is_file()]


def _search(username: str, query: str) -> list[dict]:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one()
        return org_library_service.search_allowed(db, user, query)


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        alice_id = _ensure_user("s3_alice", "Alice")
        bob_id = _ensure_user("s3_bob", "Bob")
        carol_id = _ensure_user("s3_carol", "Carol")
        dave_id = _ensure_user("s3_dave", "Dave")

        org_id = _ensure_org(
            "S3 组织", "s3-org", roles={alice_id: "admin", bob_id: "collaborator", carol_id: "member"}
        )
        other_org_id = _ensure_org("S3 其它组织", "s3-other-org", roles={dave_id: "admin"})

        yield _Ctx(
            client=client,
            alice=_login(client, "s3_alice"),
            bob=_login(client, "s3_bob"),
            carol=_login(client, "s3_carol"),
            dave=_login(client, "s3_dave"),
            org_id=org_id,
            other_org_id=other_org_id,
        )


# --------------------------------------------------------------------------- #
# 上传与解析
# --------------------------------------------------------------------------- #
def test_upload_pdf_and_docx_are_parsed_ready(ctx: _Ctx) -> None:
    pdf = _upload(
        ctx,
        ctx.alice,
        "S3 迎新策划（PDF）",
        name="orientation.pdf",
        data=_pdf_bytes("orientation plan venue layout"),
    )
    assert pdf["resource_type"] == "file"
    assert pdf["file_name"] == "orientation.pdf"
    assert pdf["file_size"] == len(_pdf_bytes("orientation plan venue layout"))
    assert pdf["text_status"] == "ready", f"PDF 未解析成功：{pdf['text_status']}"
    assert pdf["allow_student_ai"] is False and pdf["archived"] is False

    docx_data = _docx_bytes(["迎新策划整体流程", "场地布置与物资清单"])
    docx = _upload(
        ctx,
        ctx.alice,
        "S3 迎新策划（DOCX）",
        name="plan.docx",
        data=docx_data,
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert docx["text_status"] == "ready", f"DOCX 未解析成功：{docx['text_status']}"

    with SessionLocal() as db:
        pdf_row = db.query(OrgResource).filter_by(id=pdf["id"]).one()
        docx_row = db.query(OrgResource).filter_by(id=docx["id"]).one()
    assert "orientation" in (pdf_row.content_text or "")
    assert "场地布置" in (docx_row.content_text or "")
    assert pdf_row.search_text and docx_row.search_text

    listed = _ok(
        ctx.client,
        "GET",
        f"/api/org-resources?org_id={ctx.org_id}",
        headers=ctx.alice,
        label="组织资料列表",
    )
    ids = {int(item["id"]) for item in listed["items"]}
    assert {int(pdf["id"]), int(docx["id"])} <= ids
    assert all("content_text" not in item for item in listed["items"]), "列表不得返回正文"


def test_parse_failure_still_saves_resource(ctx: _Ctx) -> None:
    created = _upload(
        ctx,
        ctx.alice,
        "损坏的 PDF",
        name="broken.pdf",
        data=b"this is not a real pdf",
    )
    assert created["text_status"] == "failed", "解析失败必须落库为 failed 而不是阻断上传"
    assert created["file_name"] == "broken.pdf"
    with SessionLocal() as db:
        row = db.query(OrgResource).filter_by(id=created["id"]).one()
    assert row.content_text is None and row.search_text is None
    assert (org_library_service.upload_root() / row.file_path).is_file(), "文件本体仍需保存"


def test_invalid_upload_returns_4001_without_writing_disk(ctx: _Ctx) -> None:
    before = len(_stored_files())
    _err(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        code=ERR_INVALID_PARAM,
        status=200,
        body={
            "org_id": ctx.org_id,
            "title": "非法扩展名",
            "file": {
                "name": "virus.exe",
                "mime": "application/octet-stream",
                "size": 3,
                "data_base64": base64.b64encode(b"abc").decode(),
            },
        },
        label="非法扩展名",
    )
    _err(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        code=ERR_INVALID_PARAM,
        status=200,
        body={
            "org_id": ctx.org_id,
            "title": "超限文件",
            "file": {
                "name": "huge.pdf",
                "mime": "application/pdf",
                "size": org_library_service.MAX_FILE_BYTES + 1,
                "data_base64": base64.b64encode(b"x").decode(),
            },
        },
        label="超过 20MB",
    )
    _err(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        code=ERR_INVALID_PARAM,
        status=200,
        body={
            "org_id": ctx.org_id,
            "title": "大小不一致",
            "file": {
                "name": "mismatch.pdf",
                "mime": "application/pdf",
                "size": 1,
                "data_base64": base64.b64encode(b"abcd").decode(),
            },
        },
        label="base64 长度与声明不一致",
    )
    _err(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        code=ERR_INVALID_PARAM,
        status=200,
        body={
            "org_id": ctx.org_id,
            "title": "同时给文件与链接",
            "url": "https://example.com/x",
            "file": {
                "name": "both.pdf",
                "mime": "application/pdf",
                "size": 4,
                "data_base64": base64.b64encode(b"%PDF").decode(),
            },
        },
        label="file 与 url 同时提供",
    )
    _err(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        code=ERR_INVALID_PARAM,
        status=200,
        body={"org_id": ctx.org_id, "title": "既无文件也无链接"},
        label="file 与 url 都缺失",
    )
    _err(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        code=ERR_INVALID_PARAM,
        status=200,
        body={"org_id": ctx.org_id, "title": "非法链接", "url": "javascript:alert(1)"},
        label="非法链接 scheme",
    )
    assert len(_stored_files()) == before, "4001 校验失败不得落盘"


def test_oversized_base64_rejected_without_decode_or_disk_write(ctx: _Ctx) -> None:
    """base64 字符串长度超过声明 size 反推上限 ⇒ 解码前即 4001，且不落盘。"""
    before = len(_stored_files())
    overlong = base64.b64encode(b"x" * 4000).decode()  # 约 5336 字符
    _err(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        code=ERR_INVALID_PARAM,
        status=200,
        body={
            "org_id": ctx.org_id,
            "title": "超长 base64",
            "file": {
                "name": "overlong.txt",
                "mime": "text/plain",
                "size": 4,
                "data_base64": overlong,
            },
        },
        label="base64 字符串超过 size 反推上限",
    )
    assert len(_stored_files()) == before, "base64 超限不得落盘"
    with SessionLocal() as db:
        assert (
            db.query(OrgResource).filter(OrgResource.title == "超长 base64").first() is None
        ), "4001 校验失败不得写库"


# --------------------------------------------------------------------------- #
# 开关 / 归档 / 检索
# --------------------------------------------------------------------------- #
def test_flags_default_off_and_link_resource(ctx: _Ctx) -> None:
    created = _ok(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        body={
            "org_id": ctx.org_id,
            "title": "迎新官网",
            "summary": "报名入口",
            "url": "https://example.com/orientation",
        },
        label="登记链接资料",
    )
    assert created["resource_type"] == "link"
    assert created["url"] == "https://example.com/orientation"
    assert created["allow_student_ai"] is False, "AI 检索开关必须默认关闭"
    assert created["archived"] is False
    assert created["text_status"] == "pending"


def test_patch_is_partial_update(ctx: _Ctx) -> None:
    created = _ok(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        body={
            "org_id": ctx.org_id,
            "title": "待更新资料",
            "summary": "原简介",
            "url": "https://example.com/before",
        },
        label="创建待更新资料",
    )
    updated = _patch(ctx, ctx.alice, int(created["id"]), {"title": "已更新标题"})
    assert updated["title"] == "已更新标题"
    assert updated["summary"] == "原简介", "未传入字段必须保持不变"
    assert updated["url"] == "https://example.com/before"

    toggled = _patch(ctx, ctx.alice, int(created["id"]), {"allow_student_ai": True})
    assert toggled["allow_student_ai"] is True
    archived = _patch(ctx, ctx.alice, int(created["id"]), {"archived": True})
    assert archived["archived"] is True

    _err(
        ctx.client,
        "PATCH",
        f"/api/org-resources/{created['id']}",
        headers=ctx.alice,
        code=ERR_INVALID_PARAM,
        status=200,
        body={},
        label="空 PATCH body",
    )
    _err(
        ctx.client,
        "PATCH",
        "/api/org-resources/99999999",
        headers=ctx.alice,
        code=ERR_NOT_FOUND,
        status=404,
        body={"title": "不存在"},
        label="PATCH 不存在资料",
    )


def test_search_allowed_follows_toggle_and_archive(ctx: _Ctx) -> None:
    created = _upload(
        ctx,
        ctx.alice,
        "检索用资料",
        name="search.txt",
        data="venue layout orientation plan details".encode("utf-8"),
        mime="text/plain",
    )
    resource_id = int(created["id"])
    assert created["text_status"] == "ready"

    assert _search("s3_carol", "venue layout") == [], "开关默认关闭时不得命中"

    _patch(ctx, ctx.alice, resource_id, {"allow_student_ai": True})
    hits = _search("s3_carol", "venue layout")
    assert any(int(item["resource_id"]) == resource_id for item in hits), "开启后应命中"
    hit = next(item for item in hits if int(item["resource_id"]) == resource_id)
    assert set(hit.keys()) == {"resource_id", "title", "snippet", "score", "org_id"}
    assert int(hit["org_id"]) == ctx.org_id
    assert int(hit["score"]) > 0
    assert isinstance(hit["snippet"], str) and 0 < len(hit["snippet"]) <= 200

    _patch(ctx, ctx.alice, resource_id, {"allow_student_ai": False})
    assert _search("s3_carol", "venue layout") == [], "关闭后必须立即不再命中（无缓存）"

    _patch(ctx, ctx.alice, resource_id, {"allow_student_ai": True, "archived": True})
    assert _search("s3_carol", "venue layout") == [], "归档资料不得被检索"

    default_list = _ok(
        ctx.client,
        "GET",
        f"/api/org-resources?org_id={ctx.org_id}",
        headers=ctx.alice,
        label="默认列表不含归档",
    )
    assert resource_id not in {int(item["id"]) for item in default_list["items"]}
    with_archived = _ok(
        ctx.client,
        "GET",
        f"/api/org-resources?org_id={ctx.org_id}&include_archived=true",
        headers=ctx.alice,
        label="含归档列表",
    )
    assert resource_id in {int(item["id"]) for item in with_archived["items"]}

    _patch(ctx, ctx.alice, resource_id, {"archived": False})
    assert any(
        int(item["resource_id"]) == resource_id for item in _search("s3_carol", "venue layout")
    ), "恢复未归档后应重新命中"


def test_search_allowed_is_scoped_to_user_orgs(ctx: _Ctx) -> None:
    created = _upload(
        ctx,
        ctx.alice,
        "跨组织不可见资料",
        name="scope.txt",
        data="venue layout secret plan".encode("utf-8"),
        mime="text/plain",
    )
    _patch(ctx, ctx.alice, int(created["id"]), {"allow_student_ai": True})
    assert _search("s3_dave", "venue layout") == [], "其它组织成员不得命中"
    assert _search("s3_carol", "") == [], "空查询不返回结果"


# --------------------------------------------------------------------------- #
# 权限与下载
# --------------------------------------------------------------------------- #
def test_member_and_outsider_cannot_manage(ctx: _Ctx) -> None:
    _err(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.carol,
        code=ERR_FORBIDDEN,
        status=403,
        body={
            "org_id": ctx.org_id,
            "title": "成员越权上传",
            "file": {
                "name": "x.txt",
                "mime": "text/plain",
                "size": 1,
                "data_base64": base64.b64encode(b"x").decode(),
            },
        },
        label="member 上传",
    )
    _err(
        ctx.client,
        "GET",
        f"/api/org-resources?org_id={ctx.org_id}",
        headers=ctx.carol,
        code=ERR_FORBIDDEN,
        status=403,
        label="member 列表",
    )
    _err(
        ctx.client,
        "GET",
        f"/api/org-resources?org_id={ctx.org_id}",
        headers=ctx.dave,
        code=ERR_FORBIDDEN,
        status=403,
        label="其它组织 admin 列表",
    )
    _err(
        ctx.client,
        "GET",
        "/api/org-resources?org_id=99999999",
        headers=ctx.alice,
        code=ERR_NOT_FOUND,
        status=404,
        label="组织不存在",
    )
    _err(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        code=ERR_NOT_FOUND,
        status=404,
        body={"org_id": 99999999, "title": "不存在的组织", "url": "https://example.com/z"},
        label="向不存在组织上传",
    )

    created = _upload(
        ctx,
        ctx.alice,
        "成员不可改",
        name="guard.txt",
        data=b"guard",
        mime="text/plain",
    )
    _err(
        ctx.client,
        "PATCH",
        f"/api/org-resources/{created['id']}",
        headers=ctx.carol,
        code=ERR_FORBIDDEN,
        status=403,
        body={"allow_student_ai": True},
        label="member 改开关",
    )


def test_download_allowed_for_org_managers(ctx: _Ctx) -> None:
    data = _pdf_bytes("download me")
    created = _upload(
        ctx,
        ctx.alice,
        "可下载资料",
        name="download.pdf",
        data=data,
    )
    detail = _ok(
        ctx.client,
        "GET",
        f"/api/org-resources?org_id={ctx.org_id}",
        headers=ctx.alice,
        label="下载前列表",
    )
    item = next(entry for entry in detail["items"] if int(entry["id"]) == int(created["id"]))
    assert item["file_name"] == "download.pdf"

    for who, headers in (("上传者", ctx.alice), ("同组织 collaborator", ctx.bob)):
        response = ctx.client.get(
            f"/api/org-resources/{created['id']}/download", headers=headers
        )
        assert response.status_code == 200, f"{who}下载失败：HTTP {response.status_code}"
        assert response.content == data, f"{who}下载内容必须与原文件一致"

    # `C-LIB-REF@1` 冻结口径：无管理者权限时统一 4040（不区分资料不存在与无权访问）。
    for who, headers in (("同组织 member", ctx.carol), ("外组织 admin", ctx.dave)):
        _err(
            ctx.client,
            "GET",
            f"/api/org-resources/{created['id']}/download",
            headers=headers,
            code=ERR_NOT_FOUND,
            status=404,
            label=f"{who}下载",
        )
    _err(
        ctx.client,
        "GET",
        "/api/org-resources/99999999/download",
        headers=ctx.alice,
        code=ERR_NOT_FOUND,
        status=404,
        label="下载不存在资料",
    )

    link = _ok(
        ctx.client,
        "POST",
        "/api/org-resources",
        headers=ctx.alice,
        body={"org_id": ctx.org_id, "title": "无文件链接", "url": "https://example.com/link"},
        label="创建链接用于下载",
    )
    _err(
        ctx.client,
        "GET",
        f"/api/org-resources/{link['id']}/download",
        headers=ctx.alice,
        code=ERR_INVALID_PARAM,
        status=200,
        label="链接资料下载",
    )