#!/usr/bin/env python
"""AIW-10 预审绑定资料版本与过期验收拒绝（契约 `C-PRECHECK-EVIDENCE@2`）。

覆盖范围（全部走真实 HTTP 行为 + 真实 SQLite 列）：

1. 资料追加新版本后旧预审标记 ``stale``，历史预审行不被改写；
2. 任务要求变化后旧预审标记 ``stale``；
3. 过期预审下 ``pass=true`` 返回 4090，且不写成员状态 / 积分 / 通知；
4. 重新预审后过期状态解除，验收通过并按既有规则加分；
5. 退回不受预审过期影响；无预审记录的提交仍可正常验收；
6. ``submission_prechecks.resource_snapshot`` 列存在，迁移可重复执行；
7. 审核者发起预审时仍按成果提交者视角取资料，与成员预审结果一致；
8. 多目标验收中一人预审过期时整体 4090，任何人都不被部分写入；
9. 旧 ``submission_prechecks`` 表缺列时幂等迁移补列，旧行快照归一为 ``[]``。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH``、``MAAS_MOCK=1``、``MAAS_API_KEY=''``、
``RUN_SCHEDULER=0``；不触碰 ``backend/campus.db``。
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw10-precheck-version-"))
_TEST_DB_PATH = _TMP_DIR / "aiw10.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import db as app_db  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    CreditLog,
    Notification,
    OrgMember,
    Organization,
    SubmissionPrecheck,
    User,
)
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

if Path(app_db.engine.url.database).resolve() != _TEST_DB_PATH.resolve():
    pytest.skip(
        "AIW-10 套件必须单文件运行；"
        f"当前 engine 指向 {app_db.engine.url.database}，避免复用其它套件的临时库",
        allow_module_level=True,
    )


def _cleanup_tmp_dir() -> None:
    """先释放引擎连接池再删库目录；Windows 上未 dispose 会因文件占用删除失败。"""
    try:
        app_db.engine.dispose()
    finally:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)


atexit.register(_cleanup_tmp_dir)

PASSWORD = "TestPass123!"
ERR_CONFLICT = 4090
STALE_MSG = "预审已过期（任务要求或引用资料已变化），请重新预审"


@dataclass
class _Ctx:
    client: TestClient
    owner: dict[str, str]
    publisher: dict[str, str]
    worker: dict[str, str]
    worker2: dict[str, str]
    ids: dict[str, int]
    org_id: int
    resource_org_id: int
    auditor_org_id: int


# --------------------------------------------------------------------------- #
# 通用 HTTP / 登录辅助（沿用 AIW-04 / AIW-06 的既有约定）
# --------------------------------------------------------------------------- #
def _request(client: TestClient, method: str, path: str, *, headers=None, body=None):
    return client.request(method, path, json=body, headers=headers or {})


def _ok(client: TestClient, method: str, path: str, *, headers=None, body=None, label="") -> dict:
    response = _request(client, method, path, headers=headers, body=body)
    try:
        payload = response.json()
    except ValueError:
        raise AssertionError(f"{label}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert payload.get("code") == 0, (
        f"{label}：期望 code=0，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    data = payload.get("data")
    assert isinstance(data, dict), f"{label}：data 不是对象（{type(data).__name__}）"
    return data


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
    payload = response.json()
    assert response.status_code == 200 and payload.get("code") == 0, (
        f"登录 {username} 失败：HTTP {response.status_code} / code={payload.get('code')}"
    )
    headers = _session_headers(response)
    client.cookies.clear()
    return headers


def _ensure_user(username: str, display_name: str, *, role: str) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(username=username, display_name=display_name, role=role, credits=0)
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
                db.add(OrgMember(org_id=int(org.id), user_id=int(user_id), role=role, status="active"))
            else:
                row.role = role
                row.status = "active"
        db.commit()
        db.refresh(org)
        return int(org.id)


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        owner_id = _ensure_user("aiw10_owner", "预审版本负责人", role="publisher")
        publisher_id = _ensure_user("aiw10_publisher", "预审版本发布者", role="publisher")
        worker_id = _ensure_user("aiw10_worker", "预审版本执行者", role="student")
        worker2_id = _ensure_user("aiw10_worker2", "预审版本执行者二", role="student")

        org_id = _ensure_org(
            "AIW10 预审版本组织",
            "aiw10-precheck-version",
            roles={
                owner_id: "collaborator",
                publisher_id: "admin",
                worker_id: "member",
                worker2_id: "member",
            },
        )
        # 资料变更用独立组织：资料范围按任务组织取「同活动 + 往期」，
        # 混用一个组织会让其他测试看到往期资料，干扰 digest 的稳定对比。
        resource_org_id = _ensure_org(
            "AIW10 预审版本资料组织",
            "aiw10-precheck-version-resource",
            roles={owner_id: "collaborator", publisher_id: "admin", worker_id: "member"},
        )
        # 审核者视角组织：管理员能看到同组织往期资料，普通成员看不到；
        # 用于回归「审核者可见范围更大时不得让成员预审误判过期」。
        auditor_org_id = _ensure_org(
            "AIW10 预审版本审核视角组织",
            "aiw10-precheck-version-auditor",
            roles={owner_id: "collaborator", publisher_id: "admin", worker_id: "member"},
        )
        yield _Ctx(
            client=client,
            owner=_login(client, "aiw10_owner"),
            publisher=_login(client, "aiw10_publisher"),
            worker=_login(client, "aiw10_worker"),
            worker2=_login(client, "aiw10_worker2"),
            ids={
                "owner": owner_id,
                "publisher": publisher_id,
                "worker": worker_id,
                "worker2": worker2_id,
            },
            org_id=org_id,
            resource_org_id=resource_org_id,
            auditor_org_id=auditor_org_id,
        )


# --------------------------------------------------------------------------- #
# 领域辅助
# --------------------------------------------------------------------------- #
def _create_activity(ctx: _Ctx, title: str, *, org_id: int | None = None) -> int:
    return int(
        _ok(
            ctx.client,
            "POST",
            "/api/activities",
            headers=ctx.owner,
            body={
                "title": title,
                "org_id": ctx.org_id if org_id is None else org_id,
                "description": "预审版本测试活动",
                "location": "大学生活动中心",
                "start_time": "2027-02-10 18:00",
                "deadline": "2027-02-10 22:00",
            },
            label=f"创建活动 {title}",
        )["id"]
    )


def _create_task(
    ctx: _Ctx,
    title: str,
    *,
    activity_id: int,
    assignee_id: int,
    org_id: int | None = None,
    **fields: Any,
) -> int:
    body: dict[str, Any] = {
        "title": title,
        "activity_id": activity_id,
        "claim_type": "assign",
        "assignee_id": assignee_id,
        "start_time": "2027-02-10 18:00",
        "deadline": "2027-02-10 22:00",
        "credit_reward": 20,
        "description": "按活动时间与地点完成工作并提交成果。",
    }
    if org_id is not None:
        body["org_id"] = org_id
    body.update(fields)
    return int(
        _ok(
            ctx.client,
            "POST",
            "/api/tasks",
            headers=ctx.publisher,
            body=body,
            label=f"创建任务 {title}",
        )["id"]
    )


def _resource(ctx: _Ctx, headers, **body: Any) -> dict:
    payload: dict[str, Any] = {
        "title": body.pop("title", "资料"),
        "url": body.pop("url", "https://example.com/resource"),
    }
    payload.update(body)
    return _ok(
        ctx.client,
        "POST",
        "/api/resources",
        headers=headers,
        body=payload,
        label=f"创建资料 {payload['title']}",
    )


def _assign(ctx: _Ctx, task_id: int, user_id: int) -> None:
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/assign",
        headers=ctx.publisher,
        body={"user_id": int(user_id)},
        label=f"指派成员 {user_id} 到任务 #{task_id}",
    )


def _progress(ctx: _Ctx, task_id: int, headers) -> None:
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/progress",
        headers=headers,
        body={"content": "开始执行"},
        label=f"提交任务 #{task_id} 进度",
    )


def _submit(ctx: _Ctx, task_id: int, headers, *, content: str) -> None:
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submit",
        headers=headers,
        body={"content": content},
        label=f"提交任务 #{task_id} 成果",
    )


def _submissions(ctx: _Ctx, task_id: int, headers) -> list[dict]:
    return _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/submissions",
        headers=headers,
        label=f"读取任务 #{task_id} 成果版本",
    )["items"]


def _precheck(ctx: _Ctx, task_id: int, submission_id: int, headers) -> dict:
    return _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submissions/{submission_id}/precheck",
        headers=headers,
        label=f"预审成果 #{submission_id}",
    )


def _verify_request(
    ctx: _Ctx,
    task_id: int,
    *,
    pass_: bool,
    user_id: int | None = None,
    submission_id: int | None = None,
    reason: str | None = None,
):
    body: dict[str, Any] = {"pass": pass_}
    if user_id is not None:
        body["user_id"] = int(user_id)
    if submission_id is not None:
        body["submission_id"] = submission_id
    if reason is not None:
        body["reason"] = reason
    return _request(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        headers=ctx.publisher,
        body=body,
    )


def _verify_ok(ctx: _Ctx, task_id: int, **kwargs: Any) -> dict:
    response = _verify_request(ctx, task_id, **kwargs)
    payload = response.json()
    assert payload.get("code") == 0, (
        f"验收任务 #{task_id} 应成功，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    data = payload.get("data")
    assert isinstance(data, dict), f"验收任务 #{task_id}：data 不是对象"
    return data


def _member_status(ctx: _Ctx, task_id: int, user_id: int) -> str | None:
    detail = _ok(ctx.client, "GET", f"/api/tasks/{task_id}", headers=ctx.publisher, label="读取任务详情")
    for member in detail.get("members", []):
        if int(member["user_id"]) == int(user_id):
            return str(member["status"])
    return None


def _latest_summary(ctx: _Ctx, task_id: int, headers, user_id: int) -> dict | None:
    rows = _submissions(ctx, task_id, headers)
    row = next(
        (item for item in rows if int(item["user_id"]) == int(user_id) and item["latest"]),
        None,
    )
    assert row is not None, f"成员 {user_id} 应有最新成果版本（实际 {rows}）"
    return row["precheck"]


def _credit_log_count(user_id: int, task_id: int) -> int:
    with SessionLocal() as db:
        return int(
            db.query(CreditLog)
            .filter(CreditLog.user_id == int(user_id), CreditLog.task_id == int(task_id))
            .count()
        )


def _verified_notification_count(user_id: int, task_id: int) -> int:
    with SessionLocal() as db:
        return int(
            db.query(Notification)
            .filter(
                Notification.user_id == int(user_id),
                Notification.task_id == int(task_id),
                Notification.title == "验收通过，积分到账",
            )
            .count()
        )


def _precheck_row(submission_id: int) -> SubmissionPrecheck:
    with SessionLocal() as db:
        row = (
            db.query(SubmissionPrecheck)
            .filter(SubmissionPrecheck.submission_id == int(submission_id))
            .order_by(SubmissionPrecheck.id.desc())
            .first()
        )
        assert row is not None, f"成果 #{submission_id} 应有预审记录"
        return row


# --------------------------------------------------------------------------- #
# 1. 资料新版本使旧预审 stale，过期预审拒绝人工验收
# --------------------------------------------------------------------------- #
def test_resource_version_change_stales_precheck_and_blocks_verify(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "预审版本-资料变更活动", org_id=ctx.resource_org_id)
    resource = _resource(
        ctx,
        ctx.publisher,
        title="预审版本-资料",
        summary="初版参考资料",
        activity_id=activity_id,
        url="https://example.com/aiw10-resource-v1",
    )
    assert int(resource["version"]) == 1

    task_id = _create_task(
        ctx,
        "预审版本-资料变更任务",
        activity_id=activity_id,
        org_id=ctx.resource_org_id,
        assignee_id=ctx.ids["worker"],
    )
    _progress(ctx, task_id, ctx.worker)
    _submit(ctx, task_id, ctx.worker, content="成果说明：2027-02-10 18:00 完成")
    submission = _submissions(ctx, task_id, ctx.worker)[0]

    before = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)
    assert before["resource_snapshot"] == [
        {
            "id": int(resource["id"]),
            "title": "预审版本-资料",
            "version": 1,
        }
    ], f"预审应记录引用资料版本（实际 {before['resource_snapshot']}）"
    old_digest = str(before["requirement_digest"])

    summary = _latest_summary(ctx, task_id, ctx.publisher, ctx.ids["worker"])
    assert summary is not None and summary["stale"] is False, f"资料未变时预审不应过期（实际 {summary}）"

    updated = _resource(
        ctx,
        ctx.publisher,
        title="预审版本-资料（修订）",
        summary="补充本届注意事项",
        activity_id=activity_id,
        resource_key=resource["resource_key"],
        url="https://example.com/aiw10-resource-v2",
    )
    assert int(updated["version"]) == 2, "同一 resource_key 应追加 v2"

    summary = _latest_summary(ctx, task_id, ctx.publisher, ctx.ids["worker"])
    assert summary is not None and summary["stale"] is True, (
        f"资料版本变化后旧预审应标记 stale（实际 {summary}）"
    )
    assert summary["requirement_digest"] == old_digest, "历史预审 digest 不应被改写"
    assert _precheck_row(int(submission["id"])).resource_snapshot == [
        {"id": int(resource["id"]), "title": "预审版本-资料", "version": 1}
    ], "资料更新只让旧预审过期，不改写历史预审行"

    blocked = _verify_request(ctx, task_id, pass_=True, user_id=ctx.ids["worker"])
    blocked_payload = blocked.json()
    assert blocked_payload.get("code") == ERR_CONFLICT, (
        f"过期预审验收应返回 4090（实际 {blocked_payload.get('code')}）"
    )
    assert blocked_payload.get("msg") == STALE_MSG, (
        f"过期提示应与契约一致（实际 {blocked_payload.get('msg')}）"
    )
    assert _member_status(ctx, task_id, ctx.ids["worker"]) == "submitted", "验收失败不得改变成员状态"
    assert _credit_log_count(ctx.ids["worker"], task_id) == 0, "验收失败不得写积分流水"
    assert _verified_notification_count(ctx.ids["worker"], task_id) == 0, "验收失败不得发通过通知"

    refreshed = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)
    assert refreshed["requirement_digest"] != old_digest, "资料变化后重新预审应产生新 digest"
    assert refreshed["resource_snapshot"] == [
        {"id": int(updated["id"]), "title": "预审版本-资料（修订）", "version": 2}
    ], f"重新预审应引用最新资料版本（实际 {refreshed['resource_snapshot']}）"

    summary = _latest_summary(ctx, task_id, ctx.publisher, ctx.ids["worker"])
    assert summary is not None and summary["stale"] is False, "重新预审后应解除过期"

    approved = _verify_ok(ctx, task_id, pass_=True, user_id=ctx.ids["worker"])
    assert approved["credited_user_ids"] == [ctx.ids["worker"]], "重新预审后验收应加分"
    assert _credit_log_count(ctx.ids["worker"], task_id) == 1, "通过后积分流水应有一条"


# --------------------------------------------------------------------------- #
# 2. 任务要求变化使旧预审 stale，过期通过被拒、重新预审后通过
# --------------------------------------------------------------------------- #
def test_requirement_change_stales_precheck_and_blocks_verify(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "预审版本-要求变更活动")
    task_id = _create_task(
        ctx,
        "预审版本-要求变更任务",
        activity_id=activity_id,
        assignee_id=ctx.ids["worker2"],
    )
    _progress(ctx, task_id, ctx.worker2)
    _submit(ctx, task_id, ctx.worker2, content="初稿：2027-02-10 18:00")
    submission = _submissions(ctx, task_id, ctx.worker2)[0]

    before = _precheck(ctx, task_id, int(submission["id"]), ctx.worker2)
    assert before["resource_snapshot"] == [], "无资料时预审快照为空列表"

    _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"deadline": "2027-02-12 18:00"},
        label="修改任务要求",
    )

    summary = _latest_summary(ctx, task_id, ctx.worker2, ctx.ids["worker2"])
    assert summary is not None and summary["stale"] is True, (
        f"任务要求变化后旧预审应标记 stale（实际 {summary}）"
    )

    blocked = _verify_request(ctx, task_id, pass_=True, user_id=ctx.ids["worker2"])
    assert blocked.json().get("code") == ERR_CONFLICT, "要求变化后过期预审不得批准"
    assert _member_status(ctx, task_id, ctx.ids["worker2"]) == "submitted", "拒绝后成员仍应待验收"
    assert _credit_log_count(ctx.ids["worker2"], task_id) == 0, "拒绝不得加分"

    _precheck(ctx, task_id, int(submission["id"]), ctx.worker2)
    summary = _latest_summary(ctx, task_id, ctx.worker2, ctx.ids["worker2"])
    assert summary is not None and summary["stale"] is False, "重新预审后应解除过期"

    approved = _verify_ok(ctx, task_id, pass_=True, user_id=ctx.ids["worker2"])
    assert approved["credited_user_ids"] == [ctx.ids["worker2"]], "重新预审后应正常加分"


# --------------------------------------------------------------------------- #
# 3. 退回与无预审记录兼容
# --------------------------------------------------------------------------- #
def test_rejection_and_missing_precheck_stay_compatible(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "预审版本-兼容活动")

    # 无预审记录的提交不阻断通过（视为未检查）
    no_precheck_task = _create_task(
        ctx,
        "预审版本-无预审任务",
        activity_id=activity_id,

        assignee_id=ctx.ids["worker"],
    )
    _progress(ctx, no_precheck_task, ctx.worker)
    _submit(ctx, no_precheck_task, ctx.worker, content="无预审：2027-02-10 18:00")
    assert _latest_summary(ctx, no_precheck_task, ctx.worker, ctx.ids["worker"]) is None, "未预审时摘要应为空"
    approved = _verify_ok(ctx, no_precheck_task, pass_=True, user_id=ctx.ids["worker"])
    assert approved["credited_user_ids"] == [ctx.ids["worker"]], "无预审记录的提交仍可按旧规则验收"

    # 过期预审只影响「通过」，退回仍可用；退回后重新提交（无预审）可再次通过
    reject_task = _create_task(
        ctx,
        "预审版本-退回任务",
        activity_id=activity_id,
        assignee_id=ctx.ids["worker2"],
    )
    _progress(ctx, reject_task, ctx.worker2)
    _submit(ctx, reject_task, ctx.worker2, content="待退回稿：2027-02-10 18:00")
    first = _submissions(ctx, reject_task, ctx.worker2)[0]
    _precheck(ctx, reject_task, int(first["id"]), ctx.worker2)

    _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{reject_task}",
        headers=ctx.publisher,
        body={"description": "补充验收要求：必须附时间地点"},
        label="修改任务说明",
    )
    assert _latest_summary(ctx, reject_task, ctx.worker2, ctx.ids["worker2"])["stale"] is True

    rejected = _verify_ok(
        ctx,
        reject_task,
        pass_=False,
        user_id=ctx.ids["worker2"],
        submission_id=int(first["id"]),
        reason="时间说明不足",
    )
    assert rejected["credited_user_ids"] == [], "退回不得加分"
    assert _member_status(ctx, reject_task, ctx.ids["worker2"]) == "rejected", "退回应把成员置为 rejected"

    _submit(ctx, reject_task, ctx.worker2, content="第二版：2027-02-10 18:00")
    second = _submissions(ctx, reject_task, ctx.worker2)[0]
    assert int(second["version"]) == 2 and second["precheck"] is None, "新稿无预审记录"
    approved = _verify_ok(ctx, reject_task, pass_=True, user_id=ctx.ids["worker2"])
    assert approved["credited_user_ids"] == [ctx.ids["worker2"]], "退回重提后仍可按旧规则验收"


# --------------------------------------------------------------------------- #
# 4. 资源视角唯一化：审核者可见更多往期资料时不得误判成员预审过期
# --------------------------------------------------------------------------- #
def test_auditor_wider_resource_visibility_does_not_stale_member_precheck(ctx: _Ctx) -> None:
    past_activity = _create_activity(ctx, "预审版本-往期活动", org_id=ctx.auditor_org_id)
    past_resource = _resource(
        ctx,
        ctx.publisher,
        title="预审版本-往期资料",
        activity_id=past_activity,
        url="https://example.com/aiw10-past-resource",
    )
    activity_id = _create_activity(ctx, "预审版本-审核视角当前活动", org_id=ctx.auditor_org_id)
    task_id = _create_task(
        ctx,
        "预审版本-审核视角任务",
        activity_id=activity_id,
        org_id=ctx.auditor_org_id,
        assignee_id=ctx.ids["worker"],
    )
    _progress(ctx, task_id, ctx.worker)
    _submit(ctx, task_id, ctx.worker, content="成果：2027-02-10 18:00")
    submission = _submissions(ctx, task_id, ctx.worker)[0]

    # 构造真实视角差异：组织管理员能看到同组织往期资料，普通成员看不到。
    publisher_items = _ok(
        ctx.client,
        "GET",
        f"/api/resources?activity_id={past_activity}",
        headers=ctx.publisher,
        label="审核者读取往期资料",
    )["items"]
    assert any(int(item["id"]) == int(past_resource["id"]) for item in publisher_items), (
        "审核者应能看到同组织往期资料"
    )
    worker_items = _ok(
        ctx.client,
        "GET",
        f"/api/resources?activity_id={past_activity}",
        headers=ctx.worker,
        label="成员读取往期资料",
    )["items"]
    assert all(int(item["id"]) != int(past_resource["id"]) for item in worker_items), (
        "成员不得看到未参与活动的资料"
    )

    before = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)
    assert before["resource_snapshot"] == [], "成员预审不应引用其不可见的往期资料"

    summary = _latest_summary(ctx, task_id, ctx.publisher, ctx.ids["worker"])
    assert summary is not None and summary["stale"] is False, (
        f"stale 应按成果提交者视角判定，不受审核者可见范围影响（实际 {summary}）"
    )

    approved = _verify_ok(ctx, task_id, pass_=True, user_id=ctx.ids["worker"])
    assert approved["credited_user_ids"] == [ctx.ids["worker"]], (
        "审核者可见更多往期资料时，成员预审不得被误判为过期"
    )


# --------------------------------------------------------------------------- #
# 5. resource_snapshot 列与幂等迁移
# --------------------------------------------------------------------------- #
def test_resource_snapshot_column_and_idempotent_migration() -> None:
    def _columns() -> set[str]:
        with app_db.engine.connect() as conn:
            return {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(submission_prechecks)").fetchall()}

    assert "resource_snapshot" in _columns(), "submission_prechecks 应新增 resource_snapshot 列"
    app_db.init_db()
    app_db.init_db()
    assert "resource_snapshot" in _columns(), "重复执行迁移不得丢失 resource_snapshot 列"

# --------------------------------------------------------------------------- #
# 6. I2 审核者发起预审：digest 仍按成果提交者视角
# --------------------------------------------------------------------------- #
def test_reviewer_precheck_uses_submitter_resource_scope(ctx: _Ctx) -> None:
    past_activity = _create_activity(ctx, "预审版本-审核者预审往期活动", org_id=ctx.auditor_org_id)
    _resource(
        ctx,
        ctx.publisher,
        title="预审版本-审核者预审往期资料",
        activity_id=past_activity,
        url="https://example.com/aiw10-reviewer-past-resource",
    )
    activity_id = _create_activity(ctx, "预审版本-审核者预审当前活动", org_id=ctx.auditor_org_id)
    task_id = _create_task(
        ctx,
        "预审版本-审核者预审任务",
        activity_id=activity_id,
        org_id=ctx.auditor_org_id,
        assignee_id=ctx.ids["worker"],
    )
    _progress(ctx, task_id, ctx.worker)
    _submit(ctx, task_id, ctx.worker, content="成果：2027-02-10 18:00")
    submission = _submissions(ctx, task_id, ctx.worker)[0]

    member_result = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)
    assert member_result["resource_snapshot"] == [], "成员看不到往期资料，快照应为空"

    # 审核者（can_review_task）发起预审：资源视角仍固定为成果提交者。
    reviewer_result = _precheck(ctx, task_id, int(submission["id"]), ctx.publisher)
    assert reviewer_result["resource_snapshot"] == member_result["resource_snapshot"], (
        f"审核者预审快照应与成员预审一致（实际 {reviewer_result['resource_snapshot']}）"
    )
    assert reviewer_result["requirement_digest"] == member_result["requirement_digest"], (
        "审核者可见更多资料不得改变 digest"
    )

    summary = _latest_summary(ctx, task_id, ctx.publisher, ctx.ids["worker"])
    assert summary is not None and summary["stale"] is False, (
        f"审核者发起的预审不应被判过期（实际 {summary}）"
    )

    approved = _verify_ok(ctx, task_id, pass_=True, user_id=ctx.ids["worker"])
    assert approved["credited_user_ids"] == [ctx.ids["worker"]], "审核者发起的最新预审应支持通过"


# --------------------------------------------------------------------------- #
# 7. I3 多目标验收：一人预审过期时整体拒绝且不部分写入
# --------------------------------------------------------------------------- #
def test_multi_target_stale_precheck_rejects_without_partial_write(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "预审版本-多目标活动")
    task_id = _create_task(
        ctx,
        "预审版本-多目标任务",
        activity_id=activity_id,
        assignee_id=ctx.ids["worker"],
    )
    _assign(ctx, task_id, ctx.ids["worker2"])
    _progress(ctx, task_id, ctx.worker)
    _progress(ctx, task_id, ctx.worker2)
    _submit(ctx, task_id, ctx.worker, content="成员一：2027-02-10 18:00")
    _submit(ctx, task_id, ctx.worker2, content="成员二：2027-02-10 18:00")

    first = _submissions(ctx, task_id, ctx.worker)[0]
    second = _submissions(ctx, task_id, ctx.worker2)[0]
    _precheck(ctx, task_id, int(first["id"]), ctx.worker)
    _precheck(ctx, task_id, int(second["id"]), ctx.worker2)

    _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"description": "补充验收要求：必须附时间地点"},
        label="修改多目标任务要求",
    )
    # 仅成员一重新预审：成员一 fresh、成员二 stale。
    _precheck(ctx, task_id, int(first["id"]), ctx.worker)
    summary_first = _latest_summary(ctx, task_id, ctx.worker, ctx.ids["worker"])
    summary_second = _latest_summary(ctx, task_id, ctx.worker2, ctx.ids["worker2"])
    assert summary_first is not None and summary_first["stale"] is False, "成员一重新预审后应 fresh"
    assert summary_second is not None and summary_second["stale"] is True, "成员二未重审应 stale"

    blocked = _verify_request(ctx, task_id, pass_=True)
    payload = blocked.json()
    assert payload.get("code") == ERR_CONFLICT, (
        f"多目标中任一预审过期应整体 4090（实际 {payload.get('code')}）"
    )
    assert payload.get("msg") == STALE_MSG

    for user_id in (ctx.ids["worker"], ctx.ids["worker2"]):
        assert _member_status(ctx, task_id, user_id) == "submitted", (
            f"成员 {user_id} 不应被部分写入验收结果"
        )
        assert _credit_log_count(user_id, task_id) == 0, "整体拒绝不得给任何成员加分"
        assert _verified_notification_count(user_id, task_id) == 0, "整体拒绝不得发通过通知"


# --------------------------------------------------------------------------- #
# 8. S3 旧表无 resource_snapshot 列的幂等迁移
# --------------------------------------------------------------------------- #
def test_legacy_precheck_table_migrates_resource_snapshot() -> None:
    legacy_db = _TMP_DIR / "legacy-precheck.db"
    legacy_db.unlink(missing_ok=True)
    legacy_engine = create_engine(f"sqlite:///{legacy_db.as_posix()}")
    legacy_session = sessionmaker(bind=legacy_engine, expire_on_commit=False)
    try:
        with legacy_engine.begin() as conn:
            conn.exec_driver_sql(
                """
                CREATE TABLE submission_prechecks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submission_id INTEGER NOT NULL,
                    requirement_digest TEXT NOT NULL,
                    checks JSON NOT NULL DEFAULT '[]',
                    verdict TEXT NOT NULL,
                    summary TEXT,
                    ai_suggestions JSON NOT NULL DEFAULT '[]',
                    mock INTEGER NOT NULL DEFAULT 0,
                    ai_error TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.exec_driver_sql(
                "INSERT INTO submission_prechecks "
                "(submission_id, requirement_digest, checks, verdict, created_at) "
                "VALUES (1, 'legacy-digest', '[]', 'pass', '2026-01-01 00:00:00')"
            )

        def _legacy_columns() -> set[str]:
            with legacy_engine.connect() as conn:
                rows = conn.exec_driver_sql("PRAGMA table_info(submission_prechecks)").fetchall()
            return {row[1] for row in rows}

        assert "resource_snapshot" not in _legacy_columns(), "旧表初始状态不应含 resource_snapshot"

        # 真实迁移入口执行两次，验证幂等。
        for _ in range(2):
            with legacy_engine.begin() as conn:
                app_db._migrate(conn)

        assert "resource_snapshot" in _legacy_columns(), "幂等迁移应补齐 resource_snapshot 列"
        with legacy_session() as db:
            row = db.get(SubmissionPrecheck, 1)
            assert row is not None, "迁移不得删除旧预审行"
            assert row.requirement_digest == "legacy-digest", "迁移不得改写旧行内容"
            assert (row.resource_snapshot or []) == [], "旧行无快照时应归一为空列表"
        with legacy_engine.connect() as conn:
            count = int(
                conn.exec_driver_sql("SELECT COUNT(*) FROM submission_prechecks").fetchone()[0]
            )
        assert count == 1, "重复迁移不得新增或删除旧行"
    finally:
        legacy_engine.dispose()