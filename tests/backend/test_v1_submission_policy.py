#!/usr/bin/env python
"""成果提交策略（契约 `C-SUBMISSION-POLICY@1`）后端行为测试。

覆盖：

1. 发布/编辑任务时非法 ``modes`` / ``allowed_exts`` 返回 4001，且不落库；
2. 合法配置被规范化写入 ``extras.acceptance``，其它 ``extras`` 键原样保留；
3. 未配置策略的历史任务：无 body 提交仍成功；
4. 已配置策略：空内容 4001；文字/链接越权 4001，成员状态与版本数不变；
5. 文件提交：通道越权 4001、扩展名越权 4001，且不落盘、不改成员状态、不新增版本；
6. 允许的文字、链接与文件路径均成功生成版本。

隔离：在导入 ``app`` 之前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立
SQLite 文件，关闭调度器并强制 ``MAAS_MOCK=1``；上传目录同样指向临时路径，
不触碰 ``backend/campus.db`` 与真实 ``uploads/``。

可独立运行：``python -m pytest tests/backend/test_v1_submission_policy.py -q``。
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

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-submission-policy-"))
_TEST_DB_PATH = _TMP_DIR / "submission_policy.db"
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
    pytest.skip("成果提交策略套件必须单文件运行", allow_module_level=True)

PASSWORD = "TestPass123!"

ERR_INVALID_PARAM = 4001

MSG_MODES_INVALID = "成果提交方式配置不合法"
MSG_EXTS_INVALID = "成果文件类型配置不合法"
MSG_ACCEPTANCE_INVALID = "成果提交策略配置不合法"
MSG_POLICY_EMPTY = "请按任务要求的成果提交方式提交"
MSG_TEXT_NOT_ALLOWED = "本任务不接受文字说明提交"
MSG_LINK_NOT_ALLOWED = "本任务不接受成果链接提交"
MSG_FILE_NOT_ALLOWED = "本任务不接受文件提交"
MSG_EXT_NOT_ALLOWED = "文件类型不在任务允许范围内"


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
        publisher_id = _ensure_user("policy-publisher", "策略发布者")
        worker_id = _ensure_user("policy-worker", "策略成员")
        org_id = _ensure_org(
            "提交策略组织",
            "submission-policy-org",
            roles={publisher_id: "collaborator", worker_id: "member"},
        )
        publisher = _login(client, "policy-publisher")
        worker = _login(client, "policy-worker")

        tasks: dict[str, int] = {}

        def create(title: str, acceptance: dict | None = None, extras_extra: dict | None = None) -> int:
            extras: dict = dict(extras_extra or {})
            if acceptance is not None:
                extras["acceptance"] = acceptance
            response = client.post(
                "/api/tasks",
                json={
                    "org_id": org_id,
                    "title": title,
                    "quota": 2,
                    "claim_type": "open",
                    "credit_reward": 2,
                    "extras": extras,
                },
                headers=publisher,
            ).json()
            assert response["code"] == 0, response["msg"]
            return int(response["data"]["id"])

        def enroll(task_id: int) -> None:
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
                json={"content": "开始准备成果"},
                headers=worker,
            ).json()
            assert progressed["code"] == 0, progressed["msg"]

        tasks["legacy"] = create("历史宽松任务")
        tasks["text_only"] = create("仅文字任务", {"modes": ["text"]})
        tasks["link_only"] = create("仅链接任务", {"modes": ["link"]})
        tasks["file_pdf"] = create(
            "仅 PDF 文件任务", {"modes": ["file"], "allowed_exts": [".pdf"]}
        )
        tasks["all"] = create(
            "三种方式任务",
            {"modes": ["text", "link", "file"], "allowed_exts": [".pdf", ".docx"]},
        )
        tasks["file_any"] = create("不限类型文件任务", {"modes": ["file"]})
        for task_id in tasks.values():
            enroll(task_id)

        yield {
            "client": client,
            "publisher": publisher,
            "worker": worker,
            "worker_id": worker_id,
            "org_id": org_id,
            "tasks": tasks,
        }


def _task_detail(ctx, task_id: int) -> dict:
    payload = ctx["client"].get(f"/api/tasks/{task_id}", headers=ctx["publisher"]).json()
    assert payload["code"] == 0, payload["msg"]
    return payload["data"]


def _member_status(ctx, task_id: int) -> str:
    members = _task_detail(ctx, task_id)["members"]
    member = [item for item in members if item["user_id"] == ctx["worker_id"]][0]
    return str(member["status"])


def _submissions(ctx, task_id: int) -> list[dict]:
    payload = ctx["client"].get(
        f"/api/tasks/{task_id}/submissions", headers=ctx["worker"]
    ).json()
    assert payload["code"] == 0, payload["msg"]
    return payload["data"]["items"]


def _upload(ctx, task_id: int, name: str, payload: bytes) -> dict:
    return ctx["client"].post(
        f"/api/tasks/{task_id}/submissions/upload",
        json={
            "file_name": name,
            "file_base64": base64.b64encode(payload).decode("ascii"),
            "content": "",
        },
        headers=ctx["worker"],
    ).json()


def test_create_rejects_illegal_acceptance(ctx) -> None:
    client, publisher = ctx["client"], ctx["publisher"]
    base = {
        "org_id": ctx["org_id"],
        "title": "非法策略任务",
        "quota": 1,
        "claim_type": "open",
    }

    empty_modes = client.post(
        "/api/tasks", json={**base, "extras": {"acceptance": {"modes": []}}}, headers=publisher
    ).json()
    assert empty_modes["code"] == ERR_INVALID_PARAM
    assert empty_modes["msg"] == MSG_MODES_INVALID

    unknown_mode = client.post(
        "/api/tasks",
        json={**base, "extras": {"acceptance": {"modes": ["text", "video"]}}},
        headers=publisher,
    ).json()
    assert unknown_mode["code"] == ERR_INVALID_PARAM
    assert unknown_mode["msg"] == MSG_MODES_INVALID

    bad_ext = client.post(
        "/api/tasks",
        json={
            **base,
            "extras": {"acceptance": {"modes": ["file"], "allowed_exts": [".exe"]}},
        },
        headers=publisher,
    ).json()
    assert bad_ext["code"] == ERR_INVALID_PARAM
    assert bad_ext["msg"] == MSG_EXTS_INVALID

    # 结构类型不合法同样要 4001，不能落成 500
    malformed = client.post(
        "/api/tasks",
        json={**base, "extras": {"acceptance": {"modes": "text"}}},
        headers=publisher,
    ).json()
    assert malformed["code"] == ERR_INVALID_PARAM
    assert malformed["msg"] in {MSG_MODES_INVALID, MSG_ACCEPTANCE_INVALID}


def test_patch_rejects_illegal_acceptance_without_writing(ctx) -> None:
    client, publisher = ctx["client"], ctx["publisher"]
    task_id = ctx["tasks"]["legacy"]

    rejected = client.patch(
        f"/api/tasks/{task_id}",
        json={"extras": {"acceptance": {"modes": ["text", "unknown"]}}},
        headers=publisher,
    ).json()
    assert rejected["code"] == ERR_INVALID_PARAM
    assert rejected["msg"] == MSG_MODES_INVALID

    rejected_ext = client.patch(
        f"/api/tasks/{task_id}",
        json={"extras": {"acceptance": {"modes": ["file"], "allowed_exts": [".zip"]}}},
        headers=publisher,
    ).json()
    assert rejected_ext["code"] == ERR_INVALID_PARAM
    assert "acceptance" not in (_task_detail(ctx, task_id)["extras"] or {})


def test_create_and_patch_normalize_acceptance(ctx) -> None:
    client, publisher = ctx["client"], ctx["publisher"]
    created = client.post(
        "/api/tasks",
        json={
            "org_id": ctx["org_id"],
            "title": "规范化策略任务",
            "quota": 1,
            "claim_type": "open",
            "extras": {
                "custom": "keep",
                "acceptance": {
                    "modes": ["file", "text", "text"],
                    "allowed_exts": [".PDF", "docx"],
                    "ai_precheck": True,
                },
            },
        },
        headers=publisher,
    ).json()
    assert created["code"] == 0, created["msg"]
    task_id = int(created["data"]["id"])
    extras = created["data"]["extras"]
    assert extras["custom"] == "keep"
    assert extras["acceptance"] == {
        "modes": ["file", "text"],
        "allowed_exts": [".pdf", ".docx"],
        "ai_precheck": True,
    }

    patched = client.patch(
        f"/api/tasks/{task_id}",
        json={"extras": {"custom": "keep", "acceptance": {"modes": ["link"]}}},
        headers=publisher,
    ).json()
    assert patched["code"] == 0, patched["msg"]
    acceptance = _task_detail(ctx, task_id)["extras"]["acceptance"]
    assert acceptance == {"modes": ["link"], "allowed_exts": [], "ai_precheck": False}


def test_legacy_task_allows_empty_submit(ctx) -> None:
    task_id = ctx["tasks"]["legacy"]
    result = ctx["client"].post(f"/api/tasks/{task_id}/submit", headers=ctx["worker"]).json()
    assert result["code"] == 0, result["msg"]
    assert _member_status(ctx, task_id) == "submitted"
    assert len(_submissions(ctx, task_id)) == 1


def test_configured_task_rejects_empty_submit(ctx) -> None:
    task_id = ctx["tasks"]["text_only"]
    result = ctx["client"].post(
        f"/api/tasks/{task_id}/submit", json={}, headers=ctx["worker"]
    ).json()
    assert result["code"] == ERR_INVALID_PARAM
    assert result["msg"] == MSG_POLICY_EMPTY
    assert _member_status(ctx, task_id) == "in_progress"
    assert _submissions(ctx, task_id) == []


def test_mode_violation_rejected(ctx) -> None:
    client, worker = ctx["client"], ctx["worker"]
    link_task = ctx["tasks"]["link_only"]
    text_rejected = client.post(
        f"/api/tasks/{link_task}/submit", json={"content": "文字说明越权"}, headers=worker
    ).json()
    assert text_rejected["code"] == ERR_INVALID_PARAM
    assert text_rejected["msg"] == MSG_TEXT_NOT_ALLOWED
    assert _member_status(ctx, link_task) == "in_progress"
    assert _submissions(ctx, link_task) == []

    text_task = ctx["tasks"]["text_only"]
    link_rejected = client.post(
        f"/api/tasks/{text_task}/submit",
        json={"resource_url": "https://example.com/report"},
        headers=worker,
    ).json()
    assert link_rejected["code"] == ERR_INVALID_PARAM
    assert link_rejected["msg"] == MSG_LINK_NOT_ALLOWED
    assert _member_status(ctx, text_task) == "in_progress"
    assert _submissions(ctx, text_task) == []


def test_file_policy_rejections_leave_state_unchanged(ctx) -> None:
    text_task = ctx["tasks"]["text_only"]
    channel_rejected = _upload(ctx, text_task, "说明.txt", "文字任务不接受文件".encode("utf-8"))
    assert channel_rejected["code"] == ERR_INVALID_PARAM
    assert channel_rejected["msg"] == MSG_FILE_NOT_ALLOWED

    pdf_task = ctx["tasks"]["file_pdf"]
    ext_rejected = _upload(ctx, pdf_task, "说明.txt", "扩展名越权".encode("utf-8"))
    assert ext_rejected["code"] == ERR_INVALID_PARAM
    assert ext_rejected["msg"] == MSG_EXT_NOT_ALLOWED

    # 不落盘：策略拒绝发生在 save_submission_file 之前，任务目录不应被创建
    assert not (_TEST_UPLOAD_ROOT / str(pdf_task)).exists()
    for task_id in (text_task, pdf_task):
        assert _member_status(ctx, task_id) == "in_progress"
        assert _submissions(ctx, task_id) == []


def test_patch_extras_merge_semantics(ctx) -> None:
    """PATCH 只传 acceptance 时保留其它 extras 键；显式 null 只删除 acceptance。"""
    client, publisher = ctx["client"], ctx["publisher"]
    created = client.post(
        "/api/tasks",
        json={
            "org_id": ctx["org_id"],
            "title": "合并语义任务",
            "quota": 1,
            "claim_type": "open",
            "extras": {"custom": "keep", "note": 1, "acceptance": {"modes": ["text"]}},
        },
        headers=publisher,
    ).json()
    assert created["code"] == 0, created["msg"]
    task_id = int(created["data"]["id"])

    replaced = client.patch(
        f"/api/tasks/{task_id}",
        json={"extras": {"acceptance": {"modes": ["link"]}}},
        headers=publisher,
    ).json()
    assert replaced["code"] == 0, replaced["msg"]
    extras = _task_detail(ctx, task_id)["extras"]
    assert extras["custom"] == "keep" and extras["note"] == 1, "其它 extras 键不得被清空"
    assert extras["acceptance"] == {
        "modes": ["link"],
        "allowed_exts": [],
        "ai_precheck": False,
    }

    removed = client.patch(
        f"/api/tasks/{task_id}",
        json={"extras": {"acceptance": None}},
        headers=publisher,
    ).json()
    assert removed["code"] == 0, removed["msg"]
    extras = _task_detail(ctx, task_id)["extras"]
    assert "acceptance" not in extras, "显式 null 应移除 acceptance 键"
    assert extras["custom"] == "keep" and extras["note"] == 1

    untouched = client.patch(
        f"/api/tasks/{task_id}", json={"extras": {}}, headers=publisher
    ).json()
    assert untouched["code"] == 0, untouched["msg"]
    assert _task_detail(ctx, task_id)["extras"] == {"custom": "keep", "note": 1}


def test_file_mode_without_allowed_exts_uses_global_whitelist(ctx) -> None:
    """``modes=["file"] + allowed_exts=[]``：沿用全局白名单，非法扩展名仍由全局校验拒绝。"""
    task_id = ctx["tasks"]["file_any"]
    allowed = _upload(ctx, task_id, "任意类型.txt", "全局白名单内文件".encode("utf-8"))
    assert allowed["code"] == 0, allowed["msg"]
    assert _member_status(ctx, task_id) == "submitted"
    assert [item["version"] for item in _submissions(ctx, task_id)] == [1]

    rejected = _upload(ctx, task_id, "任意类型.exe", b"MZ")
    assert rejected["code"] == ERR_INVALID_PARAM
    assert "TXT" in rejected["msg"], "应由全局白名单文案拒绝"
    assert len(_submissions(ctx, task_id)) == 1, "拒绝后不得新增版本"


def test_allowed_paths_succeed(ctx) -> None:
    client, worker = ctx["client"], ctx["worker"]

    text_task = ctx["tasks"]["all"]
    text_result = client.post(
        f"/api/tasks/{text_task}/submit",
        json={"content": "已完成成果整理，明细见说明段落。"},
        headers=worker,
    ).json()
    assert text_result["code"] == 0, text_result["msg"]
    text_items = _submissions(ctx, text_task)
    assert [item["version"] for item in text_items] == [1]
    assert _member_status(ctx, text_task) == "submitted"

    link_task = ctx["tasks"]["link_only"]
    link_result = client.post(
        f"/api/tasks/{link_task}/submit",
        json={"resource_url": "https://example.com/report"},
        headers=worker,
    ).json()
    assert link_result["code"] == 0, link_result["msg"]
    assert _submissions(ctx, link_task)[0]["resource_url"] == "https://example.com/report"

    pdf_task = ctx["tasks"]["file_pdf"]
    file_result = _upload(ctx, pdf_task, "成果说明.pdf", b"%PDF-1.4 fake")
    assert file_result["code"] == 0, file_result["msg"]
    file_items = _submissions(ctx, pdf_task)
    assert [item["version"] for item in file_items] == [1]
    assert file_items[0]["file_name"] == "成果说明.pdf"
    assert _member_status(ctx, pdf_task) == "submitted"