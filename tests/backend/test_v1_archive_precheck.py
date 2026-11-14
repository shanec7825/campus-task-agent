#!/usr/bin/env python
"""S5 成果正文预审与优秀成果归档（契约 `C-PRECHECK-TEXT@2` / `C-ARCHIVE@1`）。

覆盖：
1. PDF / DOCX 成果在无文字说明时参与预审（`content_present` 通过）；
2. 解析失败的 PDF 保持既有拒绝口径（`content_present` fail、verdict fail、给出提示）；
3. 未验收成果归档 → 4001；无验收权 → 4030；提交/组织不存在 → 4040；
4. 归档成功后复制文件、`allow_student_ai=False`、`archived=False`、正文可解析，
   且 `search_allowed` 不命中（默认关闭）；
5. 链接成果归档为 `link` 资料；
6. 同一成果重复归档生成两行独立资料。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH`` / ``ORG_LIBRARY_UPLOAD_ROOT``、
``MAAS_MOCK=1``、``RUN_SCHEDULER=0``；成果上传根在 fixture 内指向临时目录，
不触碰 ``backend/campus.db``、``backend/uploads``。可独立运行：
``python -m pytest tests/backend/test_v1_archive_precheck.py -q``。
"""

from __future__ import annotations

import atexit
import base64
import io
import os
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-archive-precheck-"))
_TEST_DB_PATH = _TMP_DIR / "archive_precheck.db"
_TEST_SUBMISSION_ROOT = _TMP_DIR / "submissions"
_TEST_ORG_ROOT = _TMP_DIR / "org-uploads"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["ORG_LIBRARY_UPLOAD_ROOT"] = str(_TEST_ORG_ROOT)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app import db as app_db  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Organization,
    OrgMember,
    OrgResource,
    Task,
    TaskSubmission,
    User,
)
from app.security import hash_password  # noqa: E402
from app.services import org_library_service, submission_service  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PASSWORD = "TestPass123!"

ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040


def _cleanup_tmp_dir() -> None:
    try:
        app_db.engine.dispose()
    finally:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)


atexit.register(_cleanup_tmp_dir)

if Path(app_db.engine.url.database).resolve() != _TEST_DB_PATH.resolve():
    pytest.skip("归档与预审套件必须单文件运行", allow_module_level=True)


@dataclass
class _Ctx:
    client: TestClient
    publisher: dict[str, str]
    worker: dict[str, str]
    worker2: dict[str, str]
    outsider: dict[str, str]
    assignee: dict[str, str]
    publisher_id: int
    worker_id: int
    worker2_id: int
    assignee_id: int
    org_id: int
    other_org_id: int


# --------------------------------------------------------------------------- #
# 最小 PDF / DOCX 生成
# --------------------------------------------------------------------------- #
def _pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def _docx_bytes(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}"><w:body>{body}</w:body></w:document>'
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


def _create_task(ctx: _Ctx, title: str) -> int:
    data = _ok(
        ctx.client,
        "POST",
        "/api/tasks",
        headers=ctx.publisher,
        body={
            "org_id": ctx.org_id,
            "title": title,
            "description": "归档与预审测试任务",
            "quota": 3,
            "claim_type": "open",
            "credit_reward": 1,
        },
        label=f"创建任务「{title}」",
    )
    return int(data["id"])


def _join(ctx: _Ctx, task_id: int, headers: dict[str, str], user_id: int) -> None:
    """报名并审批通过；任务进入 in_progress 后不能再报名，故多成员须先各自报名。"""
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/apply",
        headers=headers,
        body={},
        label=f"报名任务 {task_id}",
    )
    items = _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/applications",
        headers=ctx.publisher,
        label=f"查看报名 {task_id}",
    )["items"]
    application = next(item for item in items if int(item["user_id"]) == int(user_id))
    _ok(
        ctx.client,
        "POST",
        f"/api/applications/{application['id']}/decide",
        headers=ctx.publisher,
        body={"approve": True},
        label=f"通过报名 {task_id}",
    )


def _progress(ctx: _Ctx, task_id: int, headers: dict[str, str]) -> None:
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/progress",
        headers=headers,
        body={"content": "开始执行"},
        label=f"推进任务 {task_id}",
    )


def _join_and_progress(ctx: _Ctx, task_id: int, headers: dict[str, str], user_id: int) -> None:
    _join(ctx, task_id, headers, user_id)
    _progress(ctx, task_id, headers)


def _upload(ctx: _Ctx, task_id: int, headers: dict[str, str], name: str, data: bytes) -> dict:
    # 上传接口返回任务详情而非版本行，这里再读一次列表拿最新版本（version/id 最大）。
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submissions/upload",
        headers=headers,
        body={
            "file_name": name,
            "file_base64": base64.b64encode(data).decode("ascii"),
            "content": "",
        },
        label=f"上传成果 {name}",
    )
    items = _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/submissions",
        headers=headers,
        label=f"读取成果版本 {name}",
    )["items"]
    assert items, f"上传 {name} 后没有成果版本"
    return max(items, key=lambda item: (int(item["version"]), int(item["id"])))


def _submit_link(ctx: _Ctx, task_id: int, headers: dict[str, str], url: str) -> None:
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submit",
        headers=headers,
        body={"resource_url": url},
        label=f"提交链接 {url}",
    )


def _precheck(ctx: _Ctx, task_id: int, submission_id: int) -> dict:
    return _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submissions/{submission_id}/precheck",
        headers=ctx.publisher,
        body={},
        label=f"预审成果 {submission_id}",
    )


def _verify(ctx: _Ctx, task_id: int, user_id: int) -> None:
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        headers=ctx.publisher,
        body={"pass": True, "user_id": int(user_id)},
        label=f"验收成员 {user_id}",
    )


def _archive(
    ctx: _Ctx,
    submission_id: int,
    *,
    org_id: int | None = None,
    title: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    body: dict[str, Any] = {
        "submission_id": int(submission_id),
        "org_id": ctx.org_id if org_id is None else int(org_id),
    }
    if title is not None:
        body["title"] = title
    return _ok(
        ctx.client,
        "POST",
        "/api/org-resources/from-submission",
        headers=headers or ctx.publisher,
        body=body,
        label=f"归档成果 {submission_id}",
    )


def _latest_submission(task_id: int, user_id: int) -> TaskSubmission:
    with SessionLocal() as db:
        row = submission_service.latest_submission(db, int(task_id), int(user_id))
    assert row is not None, "缺少成果版本"
    return row


def _checks_by_key(precheck: dict) -> dict[str, dict]:
    return {str(item["key"]): item for item in precheck["checks"]}


def _search(username: str, query: str) -> list[dict]:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one()
        return org_library_service.search_allowed(db, user, query)


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    submission_service.SUBMISSION_UPLOAD_ROOT = _TEST_SUBMISSION_ROOT
    with TestClient(app) as client:
        publisher_id = _ensure_user("s5_publisher", "S5 辅导员")
        worker_id = _ensure_user("s5_worker", "S5 成员甲")
        worker2_id = _ensure_user("s5_worker2", "S5 成员乙")
        outsider_id = _ensure_user("s5_outsider", "S5 外组织管理员")
        assignee_id = _ensure_user("s5_assignee", "S5 被指派协作者")

        org_id = _ensure_org(
            "S5 组织",
            "s5-org",
            roles={
                publisher_id: "admin",
                worker_id: "member",
                worker2_id: "member",
                assignee_id: "collaborator",
            },
        )
        other_org_id = _ensure_org(
            "S5 其它组织", "s5-other-org", roles={outsider_id: "admin"}
        )

        yield _Ctx(
            client=client,
            publisher=_login(client, "s5_publisher"),
            worker=_login(client, "s5_worker"),
            worker2=_login(client, "s5_worker2"),
            outsider=_login(client, "s5_outsider"),
            assignee=_login(client, "s5_assignee"),
            publisher_id=publisher_id,
            worker_id=worker_id,
            worker2_id=worker2_id,
            assignee_id=assignee_id,
            org_id=org_id,
            other_org_id=other_org_id,
        )


# --------------------------------------------------------------------------- #
# 1. 预审正文
# --------------------------------------------------------------------------- #
def test_pdf_and_docx_precheck_use_extracted_text(ctx: _Ctx) -> None:
    task_id = _create_task(ctx, "S5 PDF 与 DOCX 预审")
    _join(ctx, task_id, ctx.worker, ctx.worker_id)
    _join(ctx, task_id, ctx.worker2, ctx.worker2_id)
    _progress(ctx, task_id, ctx.worker)
    _progress(ctx, task_id, ctx.worker2)

    pdf = _upload(ctx, task_id, ctx.worker, "plan.pdf", _pdf_bytes("venue layout 2026-05-01"))
    docx = _upload(
        ctx, task_id, ctx.worker2, "plan.docx", _docx_bytes(["迎新策划流程", "场地布置清单"])
    )

    for label, submission in (("PDF", pdf), ("DOCX", docx)):
        precheck = _precheck(ctx, task_id, int(submission["id"]))
        checks = _checks_by_key(precheck)
        assert checks["content_present"]["status"] == "pass", (
            f"{label} 正文未参与预审：{checks['content_present']}"
        )
        assert precheck["verdict"] != "fail", f"{label} 预审不应因缺少正文而失败"
        assert precheck["ai_error"] is None, f"{label} 已解析正文却记录了取文失败提示"


def test_broken_pdf_precheck_stays_rejected(ctx: _Ctx) -> None:
    task_id = _create_task(ctx, "S5 解析失败预审")
    _join_and_progress(ctx, task_id, ctx.worker, ctx.worker_id)
    broken = _upload(ctx, task_id, ctx.worker, "broken.pdf", b"not a real pdf")

    precheck = _precheck(ctx, task_id, int(broken["id"]))
    checks = _checks_by_key(precheck)
    assert checks["content_present"]["status"] == "fail", "解析失败不得产生虚假通过"
    assert precheck["verdict"] == "fail"
    assert precheck["ai_error"], "解析失败应保留取文失败的提示"


# --------------------------------------------------------------------------- #
# 2. 归档校验
# --------------------------------------------------------------------------- #
def _verified_pdf_submission(ctx: _Ctx, title: str, text: str) -> tuple[int, int]:
    task_id = _create_task(ctx, title)
    _join_and_progress(ctx, task_id, ctx.worker, ctx.worker_id)
    created = _upload(ctx, task_id, ctx.worker, "result.pdf", _pdf_bytes(text))
    _verify(ctx, task_id, ctx.worker_id)
    return task_id, int(created["id"])


def test_archive_unverified_returns_4001(ctx: _Ctx) -> None:
    task_id = _create_task(ctx, "S5 未验收不可归档")
    _join_and_progress(ctx, task_id, ctx.worker, ctx.worker_id)
    created = _upload(ctx, task_id, ctx.worker, "draft.pdf", _pdf_bytes("draft only"))
    with SessionLocal() as db:
        before = db.query(OrgResource).count()

    _err(
        ctx.client,
        "POST",
        "/api/org-resources/from-submission",
        headers=ctx.publisher,
        code=ERR_INVALID_PARAM,
        status=200,
        body={"submission_id": int(created["id"]), "org_id": ctx.org_id},
        label="未验收归档",
    )
    with SessionLocal() as db:
        assert db.query(OrgResource).count() == before, "4001 校验失败不得写资料行"


def test_archive_requires_review_permission_4030(ctx: _Ctx) -> None:
    _, submission_id = _verified_pdf_submission(ctx, "S5 归档权限", "verified content")
    _err(
        ctx.client,
        "POST",
        "/api/org-resources/from-submission",
        headers=ctx.outsider,
        code=ERR_FORBIDDEN,
        status=403,
        body={"submission_id": submission_id, "org_id": ctx.other_org_id},
        label="无验收权归档",
    )


def test_assigned_collaborator_cannot_archive_others_submission(ctx: _Ctx) -> None:
    """归档等同成果审核（窄口径）：被指派成员即便是目标组织 collaborator 也不得归档。"""
    task_id, submission_id = _verified_pdf_submission(
        ctx, "S5 指派成员不可归档", "assignee guard content"
    )
    with SessionLocal() as db:
        task = db.get(Task, int(task_id))
        assert task is not None
        task.assignee_id = ctx.assignee_id
        db.commit()
        before = db.query(OrgResource).count()

    _err(
        ctx.client,
        "POST",
        "/api/org-resources/from-submission",
        headers=ctx.assignee,
        code=ERR_FORBIDDEN,
        status=403,
        body={"submission_id": submission_id, "org_id": ctx.org_id},
        label="被指派 collaborator 归档他人成果",
    )
    with SessionLocal() as db:
        assert db.query(OrgResource).count() == before, "越权归档不得写资料行"


def test_archive_org_permission_and_not_found(ctx: _Ctx) -> None:
    _, submission_id = _verified_pdf_submission(ctx, "S5 归档组织校验", "org check content")
    _err(
        ctx.client,
        "POST",
        "/api/org-resources/from-submission",
        headers=ctx.publisher,
        code=ERR_FORBIDDEN,
        status=403,
        body={"submission_id": submission_id, "org_id": ctx.other_org_id},
        label="归档到不可管理组织",
    )
    _err(
        ctx.client,
        "POST",
        "/api/org-resources/from-submission",
        headers=ctx.publisher,
        code=ERR_NOT_FOUND,
        status=404,
        body={"submission_id": submission_id, "org_id": 99999999},
        label="归档到不存在组织",
    )
    _err(
        ctx.client,
        "POST",
        "/api/org-resources/from-submission",
        headers=ctx.publisher,
        code=ERR_NOT_FOUND,
        status=404,
        body={"submission_id": 99999999, "org_id": ctx.org_id},
        label="归档不存在成果",
    )


# --------------------------------------------------------------------------- #
# 3. 归档行为
# --------------------------------------------------------------------------- #
def test_archive_file_defaults_off_and_search_miss(ctx: _Ctx) -> None:
    task_title = "S5 优秀成果归档"
    task_id, submission_id = _verified_pdf_submission(
        ctx, task_title, "venue layout orientation plan"
    )
    created = _archive(ctx, submission_id)

    assert created["resource_type"] == "file"
    assert created["allow_student_ai"] is False, "归档资料必须默认关闭学生 AI 检索"
    assert created["archived"] is False
    assert created["text_status"] == "ready"
    assert task_title in created["title"] and "S5 成员甲" in created["title"]
    assert task_title in (created["summary"] or "")
    assert created["file_name"] == "result.pdf"

    with SessionLocal() as db:
        row = db.get(OrgResource, int(created["id"]))
        assert row is not None and row.content_text and "venue" in row.content_text
        copied = org_library_service.upload_root() / str(row.file_path)
        assert copied.is_file(), "归档必须复制成果文件到组织资料目录"
        source = submission_service.SUBMISSION_UPLOAD_ROOT / str(row.file_path)
        assert not source.is_file(), "组织资料文件路径不能落在成果上传目录"

    assert _search("s5_worker", "venue layout") == [], "默认关闭时学生检索不得命中"

    again = _archive(ctx, submission_id)
    assert int(again["id"]) != int(created["id"]), "重复归档应生成新的资料行"
    assert again["title"] == created["title"]
    with SessionLocal() as db:
        rows = (
            db.query(OrgResource)
            .filter(OrgResource.created_by == ctx.publisher_id, OrgResource.title == created["title"])
            .all()
        )
    assert len(rows) == 2
    assert len({str(row.file_path) for row in rows}) == 2, "重复归档的复制文件必须独立"


def test_archive_link_submission(ctx: _Ctx) -> None:
    task_id = _create_task(ctx, "S5 链接成果归档")
    _join_and_progress(ctx, task_id, ctx.worker, ctx.worker_id)
    _submit_link(ctx, task_id, ctx.worker, "https://example.com/s5-result")
    submission = _latest_submission(task_id, ctx.worker_id)
    _verify(ctx, task_id, ctx.worker_id)

    created = _archive(ctx, int(submission.id), title="S5 链接归档资料")
    assert created["title"] == "S5 链接归档资料"
    assert created["resource_type"] == "link"
    assert created["url"] == "https://example.com/s5-result"
    assert created["file_name"] is None
    assert created["allow_student_ai"] is False
    assert created["text_status"] == "pending"
    assert _search("s5_worker", "s5 result") == [], "链接资料默认不参与学生检索"