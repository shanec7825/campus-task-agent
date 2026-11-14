#!/usr/bin/env python
"""成果文件链路（契约 `C-SUBMISSION-FILE@1`）。

覆盖：成员上传 TXT 生成版本并置 submitted、列表返回文件信息、本人/审核者可下载、
非成员下载被拒、非法格式与超限 4001、迁移列存在。

隔离：临时 DATABASE_PATH / MAAS_MOCK / RUN_SCHEDULER；上传目录用临时路径。
"""

from __future__ import annotations

import atexit
import base64
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-submission-file-"))
_TEST_DB_PATH = _TMP_DIR / "submission.db"
_TEST_UPLOAD_ROOT = _TMP_DIR / "uploads"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app import db as app_db  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Organization, OrgMember, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import submission_service  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402


def _cleanup_tmp_dir() -> None:
    try:
        app_db.engine.dispose()
    finally:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)


atexit.register(_cleanup_tmp_dir)

if Path(app_db.engine.url.database).resolve() != _TEST_DB_PATH.resolve():
    pytest.skip("成果文件套件必须单文件运行", allow_module_level=True)

PASSWORD = "TestPass123!"


def _ensure_user(username: str, display_name: str) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(
                username=username,
                display_name=display_name,
                role="student",
                password_hash=hash_password(PASSWORD),
                status="active",
            )
            db.add(user)
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
                db.add(OrgMember(org_id=int(org.id), user_id=int(user_id), role=role, status="active"))
            else:
                row.role = role
                row.status = "active"
        db.commit()
        db.refresh(org)
        return int(org.id)


def _session_headers(response) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in response.headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        if name.strip() in {SESSION_COOKIE, CSRF_COOKIE}:
            values[name.strip()] = rest.split(";", 1)[0].strip()
    assert values.get(SESSION_COOKIE) and values.get(CSRF_COOKIE), "登录响应缺少会话 Cookie"
    return {
        "Cookie": f"{SESSION_COOKIE}={values[SESSION_COOKIE]}; {CSRF_COOKIE}={values[CSRF_COOKIE]}",
        CSRF_HEADER: values[CSRF_COOKIE],
    }


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    payload = response.json()
    assert payload.get("code") == 0, f"登录失败：{payload.get('msg')}"
    client.cookies.clear()
    return _session_headers(response)


@pytest.fixture(scope="module")
def ctx():
    submission_service.SUBMISSION_UPLOAD_ROOT = _TEST_UPLOAD_ROOT
    with TestClient(app) as client:
        publisher_id = _ensure_user("file-publisher", "文件发布者")
        worker_id = _ensure_user("file-worker", "文件成员")
        outsider_id = _ensure_user("file-outsider", "文件外部")
        org_id = _ensure_org(
            "成果文件组织",
            "submission-file-org",
            roles={publisher_id: "collaborator", worker_id: "member"},
        )
        publisher = _login(client, "file-publisher")
        worker = _login(client, "file-worker")
        outsider = _login(client, "file-outsider")

        created = client.post(
            "/api/tasks",
            json={
                "org_id": org_id,
                "title": "成果文件上传任务",
                "quota": 2,
                "claim_type": "open",
                "credit_reward": 2,
            },
            headers=publisher,
        ).json()
        assert created["code"] == 0, created["msg"]
        task_id = int(created["data"]["id"])

        applied = client.post(f"/api/tasks/{task_id}/apply", json={}, headers=worker).json()
        assert applied["code"] == 0, applied["msg"]
        apps = client.get(f"/api/tasks/{task_id}/applications", headers=publisher).json()
        application_id = int(apps["data"]["items"][0]["id"])
        decided = client.post(
            f"/api/applications/{application_id}/decide",
            json={"approve": True},
            headers=publisher,
        ).json()
        assert decided["code"] == 0, decided["msg"]

        progressed = client.post(
            f"/api/tasks/{task_id}/progress",
            json={"content": "开始准备成果文件"},
            headers=worker,
        ).json()
        assert progressed["code"] == 0, progressed["msg"]

        yield {
            "client": client,
            "publisher": publisher,
            "worker": worker,
            "outsider": outsider,
            "task_id": task_id,
            "worker_id": worker_id,
        }


def _upload(ctx, name: str, payload: bytes, content_type: str = "", *, headers=None):
    return ctx["client"].post(
        f"/api/tasks/{ctx['task_id']}/submissions/upload",
        json={
            "file_name": name,
            "file_base64": base64.b64encode(payload).decode("ascii"),
            "content": "",
        },
        headers=headers or ctx["worker"],
    ).json()


def test_upload_creates_version_and_download(ctx) -> None:
    payload = "活动签到与物料清点已完成，现场照片见附件。".encode("utf-8")
    result = _upload(ctx, "成果说明.txt", payload, "text/plain")
    assert result["code"] == 0, result["msg"]

    detail = ctx["client"].get(f"/api/tasks/{ctx['task_id']}", headers=ctx["publisher"]).json()
    assert detail["code"] == 0
    member = [m for m in detail["data"]["members"] if m["user_id"] == ctx["worker_id"]][0]
    assert member["status"] == "submitted"

    submissions = ctx["client"].get(
        f"/api/tasks/{ctx['task_id']}/submissions", headers=ctx["worker"]
    ).json()["data"]["items"]
    assert len(submissions) == 1
    item = submissions[0]
    assert item["file_name"] == "成果说明.txt"
    assert item["file_size"] == len(payload)
    assert item["file_mime"] == "text/plain"

    own = ctx["client"].get(
        f"/api/tasks/{ctx['task_id']}/submissions/{item['id']}/file", headers=ctx["worker"]
    )
    assert own.status_code == 200 and own.content == payload

    reviewer = ctx["client"].get(
        f"/api/tasks/{ctx['task_id']}/submissions/{item['id']}/file", headers=ctx["publisher"]
    )
    assert reviewer.status_code == 200 and reviewer.content == payload

    denied = ctx["client"].get(
        f"/api/tasks/{ctx['task_id']}/submissions/{item['id']}/file", headers=ctx["outsider"]
    )
    if denied.headers.get("content-type", "").startswith("application/json"):
        assert denied.json()["code"] in {4030, 4040}
    else:
        assert denied.status_code in {403, 404}


def test_invalid_format_and_size_rejected(ctx) -> None:
    bad = _upload(ctx, "成果.exe", b"MZ", "application/octet-stream")
    assert bad["code"] == 4001

    oversized = _upload(ctx, "大文件.txt", b"x" * (10 * 1024 * 1024 + 1), "text/plain")
    assert oversized["code"] == 4001
    assert "10MB" in oversized["msg"]


def test_precheck_uses_text_file_and_skips_pdf(ctx) -> None:
    item = ctx["client"].get(
        f"/api/tasks/{ctx['task_id']}/submissions", headers=ctx["worker"]
    ).json()["data"]["items"][0]
    pre = ctx["client"].post(
        f"/api/tasks/{ctx['task_id']}/submissions/{item['id']}/precheck",
        json={},
        headers=ctx["publisher"],
    ).json()
    assert pre["code"] == 0
    assert pre["data"]["resource_snapshot"] == []

    rejected = ctx["client"].post(
        f"/api/tasks/{ctx['task_id']}/verify",
        json={"pass": False, "reason": "请补充 PDF 说明", "user_id": ctx["worker_id"]},
        headers=ctx["publisher"],
    ).json()
    assert rejected["code"] == 0, rejected["msg"]

    pdf = _upload(ctx, "说明.pdf", b"%PDF-1.4 fake", "application/pdf")
    assert pdf["code"] == 0, pdf["msg"]
    latest = ctx["client"].get(
        f"/api/tasks/{ctx['task_id']}/submissions", headers=ctx["worker"]
    ).json()["data"]["items"][0]
    assert latest["file_name"] == "说明.pdf"


def test_migration_columns_exist(ctx) -> None:
    with SessionLocal() as db:
        columns = {
            row[1] for row in db.execute(__import__("sqlalchemy").text("PRAGMA table_info(task_submissions)")).fetchall()
        }
    assert {"file_name", "file_size", "file_mime", "file_path"} <= columns
    app_db.init_db()  # 可重复执行