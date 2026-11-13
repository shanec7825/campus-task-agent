#!/usr/bin/env python
"""AIW-04 资料与成果审核后端行为测试（契约 `C-RESOURCE@1` / `C-SUBMISSION@1` / `C-PRECHECK@1`）。

覆盖范围（全部走真实 HTTP 行为）：

1. 资料创建权限、归属冲突与版本追加；
2. 权限内检索：组织内可见、跨组织不可见、任务相关资料含同活动与往期；
3. 成果版本：提交生成 v1、退回后再提交生成 v2、重复提交不新增版本；
4. 成果可见性：发布者看全部、普通成员只看自己、无关用户 4040；
5. 规则预审：错误时间 fail 并有证据、正确时间 pass、缺要求 unknown；
6. 预审不改变任务/成员/积分，且模型 mock 标记真实；
7. 旧版本验收 4090、最新版本验收通过并幂等加分；
8. 预审权限：普通成员不能预审他人、无关用户 4040；
9. 任务要求变化后旧预审标记 stale。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH``、``MAAS_MOCK=1``、``MAAS_API_KEY=''``、
``RUN_SCHEDULER=0``；不触碰 ``backend/campus.db``。
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw04-resource-review-"))
_TEST_DB_PATH = _TMP_DIR / "aiw04.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    ActivityResource,
    CreditLog,
    OrgMember,
    Organization,
    SubmissionPrecheck,
    Task,
    TaskSubmission,
    User,
)
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040
ERR_CONFLICT = 4090
PASSWORD = "TestPass123!"


@dataclass
class _Ctx:
    client: TestClient
    owner: dict[str, str]
    publisher: dict[str, str]
    worker: dict[str, str]
    worker2: dict[str, str]
    outsider: dict[str, str]
    foreign_admin: dict[str, str]
    ids: dict[str, int]
    org_id: int
    foreign_org_id: int


def _request(client: TestClient, method: str, path: str, *, headers=None, body=None):
    return client.request(method, path, json=body, headers=headers or {})


def _payload(client: TestClient, method: str, path: str, *, headers=None, body=None, label=""):
    response = _request(client, method, path, headers=headers, body=body)
    try:
        payload = response.json()
    except ValueError:
        raise AssertionError(f"{label}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert isinstance(payload, dict), f"{label}：响应体不是对象（HTTP {response.status_code}）"
    return payload


def _ok(client: TestClient, method: str, path: str, *, headers=None, body=None, label="") -> dict:
    payload = _payload(client, method, path, headers=headers, body=body, label=label)
    assert payload.get("code") == 0, (
        f"{label}：期望 code=0，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    data = payload.get("data")
    assert isinstance(data, dict), f"{label}：data 不是对象（{type(data).__name__}）"
    return data


def _err(
    client: TestClient,
    method: str,
    path: str,
    *,
    code: int,
    headers=None,
    body=None,
    label="",
    status: int = 200,
) -> dict:
    response = _request(client, method, path, headers=headers, body=body)
    payload = response.json()
    assert payload.get("code") == code, (
        f"{label}：期望 code={code}，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    assert response.status_code == status, (
        f"{label}：期望 HTTP {status}，实际 HTTP {response.status_code}"
    )
    return payload


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
        owner_id = _ensure_user("aiw04_owner", "资料负责人", role="publisher")
        publisher_id = _ensure_user("aiw04_publisher", "资料发布者", role="publisher")
        worker_id = _ensure_user("aiw04_worker", "资料执行者", role="student")
        worker2_id = _ensure_user("aiw04_worker2", "资料执行者二", role="student")
        outsider_id = _ensure_user("aiw04_outsider", "资料路人", role="student")
        foreign_admin_id = _ensure_user("aiw04_foreign", "外组织管理员", role="publisher")

        org_id = _ensure_org(
            "AIW04 资料审核组织",
            "aiw04-resource-review",
            roles={
                owner_id: "collaborator",
                publisher_id: "admin",
                worker_id: "member",
                worker2_id: "member",
            },
        )
        foreign_org_id = _ensure_org(
            "AIW04 外组织",
            "aiw04-foreign",
            roles={outsider_id: "member", foreign_admin_id: "admin"},
        )
        yield _Ctx(
            client=client,
            owner=_login(client, "aiw04_owner"),
            publisher=_login(client, "aiw04_publisher"),
            worker=_login(client, "aiw04_worker"),
            worker2=_login(client, "aiw04_worker2"),
            outsider=_login(client, "aiw04_outsider"),
            foreign_admin=_login(client, "aiw04_foreign"),
            ids={
                "owner": owner_id,
                "publisher": publisher_id,
                "worker": worker_id,
                "worker2": worker2_id,
                "outsider": outsider_id,
                "foreign_admin": foreign_admin_id,
            },
            org_id=org_id,
            foreign_org_id=foreign_org_id,
        )


def _create_activity(ctx: _Ctx, title: str, *, org_id: int | None = None, **fields: Any) -> int:
    return int(
        _ok(
            ctx.client,
            "POST",
            "/api/activities",
            headers=ctx.owner,
            body={"title": title, "org_id": ctx.org_id if org_id is None else org_id, **fields},
            label=f"创建活动 {title}",
        )["id"]
    )


def _create_task(ctx: _Ctx, title: str, *, activity_id: int | None = None, **fields: Any) -> dict:
    body: dict[str, Any] = {"title": title}
    if activity_id is not None:
        body["activity_id"] = activity_id
    body.update(fields)
    return _ok(
        ctx.client,
        "POST",
        "/api/tasks",
        headers=ctx.publisher,
        body=body,
        label=f"创建任务 {title}",
    )


def _assign(ctx: _Ctx, task_id: int, user_id: int) -> dict:
    return _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/assign",
        headers=ctx.publisher,
        body={"user_id": user_id},
        label=f"指派成员 {user_id} 到任务 #{task_id}",
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


def _submissions(ctx: _Ctx, task_id: int, headers) -> list[dict]:
    return _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/submissions",
        headers=headers,
        label=f"读取任务 #{task_id} 成果版本",
    )["items"]


def _submit(ctx: _Ctx, task_id: int, headers, *, content: str, resource_url: str | None = None) -> dict:
    body: dict[str, Any] = {"content": content}
    if resource_url is not None:
        body["resource_url"] = resource_url
    return _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submit",
        headers=headers,
        body=body,
        label=f"提交任务 #{task_id} 成果",
    )


def _precheck(ctx: _Ctx, task_id: int, submission_id: int, headers) -> dict:
    return _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submissions/{submission_id}/precheck",
        headers=headers,
        label=f"预审成果 #{submission_id}",
    )


def _time_check(result: dict) -> dict:
    return next(item for item in result["checks"] if item["key"] == "time_consistency")


# --------------------------------------------------------------------------- #
# 1. 资料权限、归属与版本
# --------------------------------------------------------------------------- #
def test_resource_permissions_versions_and_scope_conflicts(ctx: _Ctx) -> None:
    activity_a = _create_activity(ctx, "资料权限-活动A")
    activity_b = _create_activity(ctx, "资料权限-活动B")
    task = _create_task(
        ctx,
        "资料权限-任务",
        activity_id=activity_a,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])

    created = _resource(
        ctx,
        ctx.publisher,
        title="资料权限-推文模板",
        summary="往届推文结构与时间写法",
        activity_id=activity_a,
        url="https://example.com/template-v1",
    )
    assert created["version"] == 1, f"新建资料应从 v1 开始（实际 {created['version']}）"
    assert created["activity_title"] == "资料权限-活动A", "返回真实来源活动标题"
    assert created["created_by"] == ctx.ids["publisher"], "返回真实创建人"

    visible = _ok(
        ctx.client,
        "GET",
        f"/api/resources?activity_id={activity_a}",
        headers=ctx.worker,
        label="组织成员读取活动资料",
    )["items"]
    assert any(item["id"] == created["id"] for item in visible), "活动下可见任务的成员应能看到资料"

    _err(
        ctx.client,
        "POST",
        "/api/resources",
        code=ERR_FORBIDDEN,
        headers=ctx.worker,
        body={"title": "越权资料", "url": "https://example.com/x", "activity_id": activity_a},
        label="普通成员创建活动资料",
        status=403,
    )

    updated = _resource(
        ctx,
        ctx.publisher,
        title="资料权限-推文模板（修订）",
        summary="补充本届注意事项",
        activity_id=activity_a,
        resource_key=created["resource_key"],
        url="https://example.com/template-v2",
    )
    assert updated["version"] == 2, f"同一 resource_key 应追加 v2（实际 {updated['version']}）"
    assert updated["resource_key"] == created["resource_key"], "版本更新不改 resource_key"

    listed = _ok(
        ctx.client,
        "GET",
        f"/api/resources?q=推文模板&activity_id={activity_a}",
        headers=ctx.worker,
        label="检索资料版本",
    )["items"]
    versions = {item["version"] for item in listed if item["resource_key"] == created["resource_key"]}
    assert versions == {1, 2}, f"旧版本应保留（实际版本 {versions}）"

    _err(
        ctx.client,
        "POST",
        "/api/resources",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={
            "title": "跨活动改归属",
            "url": "https://example.com/moved",
            "activity_id": activity_b,
            "resource_key": created["resource_key"],
        },
        label="资料新版本改变归属",
    )
    _err(
        ctx.client,
        "POST",
        "/api/resources",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={"title": "无归属资料", "url": "https://example.com/none"},
        label="无归属资料",
    )
    _err(
        ctx.client,
        "POST",
        "/api/resources",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={
            "title": "归属冲突资料",
            "url": "https://example.com/conflict",
            "task_id": task_id,
            "activity_id": activity_b,
        },
        label="任务与活动归属冲突",
    )


# --------------------------------------------------------------------------- #
# 2. 权限内检索：同组织跨活动可见，跨组织不出现
# --------------------------------------------------------------------------- #
def test_resource_search_related_and_cross_org_isolation(ctx: _Ctx) -> None:
    activity_current = _create_activity(ctx, "检索-本届活动")
    activity_past = _create_activity(ctx, "检索-往届活动")
    task = _create_task(
        ctx,
        "检索-本届推文",
        activity_id=activity_current,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    past_task = _create_task(
        ctx,
        "检索-往届推文",
        activity_id=activity_past,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    assert int(task["id"]) and int(past_task["id"])

    current_resource = _resource(
        ctx,
        ctx.publisher,
        title="检索-本届推文要求",
        summary="本届晚会时间地点",
        activity_id=activity_current,
        url="https://example.com/current",
    )
    past_resource = _resource(
        ctx,
        ctx.owner,
        title="检索-往届推文模板",
        summary="往届推文结构与句式",
        activity_id=activity_past,
        url="https://example.com/past",
    )

    foreign_activity = int(
        _ok(
            ctx.client,
            "POST",
            "/api/activities",
            headers=ctx.foreign_admin,
            body={"title": "检索-外组织活动", "org_id": ctx.foreign_org_id},
            label="外组织创建活动",
        )["id"]
    )
    foreign_resource = _resource(
        ctx,
        ctx.foreign_admin,
        title="检索-外组织机密模板",
        summary="不应被其他组织看到",
        activity_id=foreign_activity,
        url="https://example.com/foreign",
    )

    found = _ok(
        ctx.client,
        "GET",
        "/api/resources?q=推文模板",
        headers=ctx.worker,
        label="跨活动检索往期资料",
    )["items"]
    found_ids = {item["id"] for item in found}
    assert past_resource["id"] in found_ids, (
        f"应命中本组织往期资料（实际 {[item['title'] for item in found]}）"
    )
    assert foreign_resource["id"] not in found_ids, "跨组织资料不得出现在检索结果"
    foreign_titles = {item["title"] for item in found}
    assert "检索-外组织机密模板" not in foreign_titles, "无权限资料的标题也不得泄露"
    past = next(item for item in found if item["id"] == past_resource["id"])
    assert past["activity_title"] == "检索-往届活动", "检索结果保留真实来源活动"
    assert past["url"] == "https://example.com/past", "返回真实原始地址"

    related = _ok(
        ctx.client,
        "GET",
        f"/api/resources?related_task_id={int(task['id'])}",
        headers=ctx.worker,
        label="任务相关资料",
    )["items"]
    related_ids = {item["id"] for item in related}
    assert {current_resource["id"], past_resource["id"]} <= related_ids, (
        f"任务相关资料应包含同活动与同组织往期资料（实际 {related_ids}）"
    )
    assert foreign_resource["id"] not in related_ids, "跨组织资料不得出现在任务相关列表"

    leaked = _ok(
        ctx.client,
        "GET",
        f"/api/resources?q={foreign_resource['title']}",
        headers=ctx.worker,
        label="按标题检索外组织资料",
    )["items"]
    assert foreign_resource["id"] not in {item["id"] for item in leaked}, "无权限资料不得出现"
    assert foreign_resource["title"] not in {item["title"] for item in leaked}, "无权限资料标题不得泄露"


# --------------------------------------------------------------------------- #
# 3. 成果版本：生成、幂等与可见性
# --------------------------------------------------------------------------- #
def test_submission_versions_and_visibility(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "版本-活动")
    task = _create_task(
        ctx,
        "版本-任务",
        activity_id=activity_id,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _assign(ctx, task_id, ctx.ids["worker2"])

    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker, body={"content": "开始执行"})
    _submit(ctx, task_id, ctx.worker, content="第一版成果", resource_url="https://example.com/v1")

    mine = _submissions(ctx, task_id, ctx.worker)
    assert len(mine) == 1 and mine[0]["version"] == 1 and mine[0]["latest"] is True, (
        f"本人应看到一条最新版本（实际 {mine}）"
    )

    publisher_view = _submissions(ctx, task_id, ctx.publisher)
    assert any(item["user_id"] == ctx.ids["worker"] and item["version"] == 1 for item in publisher_view), (
        "发布者应能看到成员成果版本"
    )

    other_member = _submissions(ctx, task_id, ctx.worker2)
    assert other_member == [], f"普通成员不得看到他人成果（实际 {other_member}）"

    _err(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/submissions",
        code=ERR_NOT_FOUND,
        headers=ctx.outsider,
        label="无关用户读取成果版本",
        status=404,
    )

    # 重复提交：成员已处于 submitted，幂等返回且不新增版本
    _submit(ctx, task_id, ctx.worker, content="重复提交不应新增")
    with SessionLocal() as db:
        count = (
            db.query(TaskSubmission)
            .filter(TaskSubmission.task_id == task_id, TaskSubmission.user_id == ctx.ids["worker"])
            .count()
        )
    assert count == 1, f"重复提交不得新增版本（实际 {count} 条）"

    # 旧的无 body 提交兼容路径：worker2 首次提交不传请求体
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker2, body={"content": "开始"})
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/submit", headers=ctx.worker2, label="旧无 body 提交")
    worker2_rows = _submissions(ctx, task_id, ctx.worker2)
    assert len(worker2_rows) == 1 and worker2_rows[0]["content"] is None, (
        f"旧调用应生成空内容版本（实际 {worker2_rows}）"
    )

    # assignee 也是普通成员：成果列表仍只能看到自己的版本
    assignee_view = _submissions(ctx, task_id, ctx.worker)
    assert {item["user_id"] for item in assignee_view} == {ctx.ids["worker"]}, (
        f"被指派的成员不得看到他人成果（实际 {assignee_view}）"
    )


# --------------------------------------------------------------------------- #
# 4. 规则预审：错误时间被指出且不改变业务状态
# --------------------------------------------------------------------------- #
def test_precheck_wrong_time_fails_with_evidence_and_no_state_change(ctx: _Ctx) -> None:
    activity_id = _create_activity(
        ctx, "预审错时-活动", start_time="2026-12-20 19:00", deadline="2026-12-20 22:00"
    )
    task = _create_task(
        ctx,
        "预审错时-任务",
        activity_id=activity_id,
        deadline="2026-12-20 19:00",
        description="写一篇晚会预热推文，时间地点须与活动一致",
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker, body={"content": "开始"})
    _submit(ctx, task_id, ctx.worker, content="推文初稿：活动将于 2026-12-21 19:00 在礼堂举行。")
    submission = _submissions(ctx, task_id, ctx.worker)[0]

    result = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)
    assert result["verdict"] == "fail", f"错误时间应判定 fail（实际 {result['verdict']}）"
    check = _time_check(result)
    assert check["status"] == "fail", f"时间检查应为 fail（实际 {check}）"
    assert "2026-12-21" in (check["evidence"] or "") and "2026-12-20" in (check["evidence"] or ""), (
        f"证据应同时给出提交与要求时间（实际 {check['evidence']!r}）"
    )
    assert result["mock"] is True, "mock 模式必须如实标注"
    assert result["ai_suggestions"] == [], "mock 模式不生成真实模型建议"

    detail = _ok(ctx.client, "GET", f"/api/tasks/{task_id}", headers=ctx.publisher, label="预审后读取任务")
    assert detail["status"] == "submitted", "预审不得改变任务聚合状态"
    member = next(item for item in detail["members"] if item["user_id"] == ctx.ids["worker"])
    assert member["status"] == "submitted", "预审不得改变成员状态"
    with SessionLocal() as db:
        credits = db.query(CreditLog).filter(CreditLog.user_id == ctx.ids["worker"], CreditLog.task_id == task_id).count()
        prechecks = db.query(SubmissionPrecheck).filter(SubmissionPrecheck.submission_id == int(submission["id"])).count()
    assert credits == 0, "预审不得发放积分"
    assert prechecks == 1, "预审应持久化一条记录"

    second = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)
    assert second["checks"] == result["checks"], "同一版本重复预审的规则结论应稳定"
    with SessionLocal() as db:
        prechecks = db.query(SubmissionPrecheck).filter(SubmissionPrecheck.submission_id == int(submission["id"])).count()
    assert prechecks == 2, "重复预审保留历史记录"


# --------------------------------------------------------------------------- #
# 5. 正确时间可通过规则检查（仍不等于验收）
# --------------------------------------------------------------------------- #
def test_precheck_correct_time_passes_rules(ctx: _Ctx) -> None:
    activity_id = _create_activity(
        ctx, "预审正确-活动", start_time="2026-12-25 19:00", deadline="2026-12-25 22:00"
    )
    task = _create_task(
        ctx,
        "预审正确-任务",
        activity_id=activity_id,
        deadline="2026-12-25 19:00",
        description="推文必须准确写明活动时间与地点",
        sop_guide="时间、地点与活动一致；提供推文链接",
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _resource(
        ctx,
        ctx.publisher,
        title="预审正确-参考资料",
        activity_id=activity_id,
        summary="本届活动时间地点说明",
    )
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker, body={"content": "开始"})
    _submit(
        ctx,
        task_id,
        ctx.worker,
        content="推文终稿：活动于 2026-12-25 19:00 在礼堂举行。",
        resource_url="https://example.com/final-post",
    )
    submission = _submissions(ctx, task_id, ctx.worker)[0]
    result = _precheck(ctx, task_id, int(submission["id"]), ctx.publisher)

    assert _time_check(result)["status"] == "pass", f"正确时间应通过（实际 {_time_check(result)}）"
    assert result["verdict"] == "pass", f"规则项均通过时 verdict 应为 pass（实际 {result['verdict']}；{result['checks']}）"
    assert result["summary"], "应返回预审摘要"
    detail = _ok(ctx.client, "GET", f"/api/tasks/{task_id}", headers=ctx.publisher, label="pass 预审后任务状态")
    assert detail["status"] == "submitted", "预审 pass 也不能自动验收"


# --------------------------------------------------------------------------- #
# 6. 缺少要求 / 无日期 → unknown，不得冒充通过
# --------------------------------------------------------------------------- #
def test_precheck_missing_requirements_stays_unknown(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "预审缺要求-活动")
    task = _create_task(
        ctx,
        "预审缺要求-任务",
        activity_id=activity_id,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker, body={"content": "开始"})
    _submit(ctx, task_id, ctx.worker, content="已完成，请查收。")
    submission = _submissions(ctx, task_id, ctx.worker)[0]

    result = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)
    assert result["verdict"] == "unknown", f"缺少可核对依据时应为 unknown（实际 {result['verdict']}）"
    assert not any(item["status"] == "fail" for item in result["checks"]), "缺信息不应伪装成失败或通过"


# --------------------------------------------------------------------------- #
# 7. 预审权限
# --------------------------------------------------------------------------- #
def test_precheck_permissions(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "预审权限-活动")
    task = _create_task(
        ctx,
        "预审权限-任务",
        activity_id=activity_id,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _assign(ctx, task_id, ctx.ids["worker2"])
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker, body={"content": "开始"})
    _submit(ctx, task_id, ctx.worker, content="成果内容")
    submission = _submissions(ctx, task_id, ctx.worker)[0]

    _err(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submissions/{int(submission['id'])}/precheck",
        code=ERR_FORBIDDEN,
        headers=ctx.worker2,
        label="普通成员预审他人成果",
        status=403,
    )
    _err(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submissions/{int(submission['id'])}/precheck",
        code=ERR_NOT_FOUND,
        headers=ctx.outsider,
        label="无关用户预审成果",
        status=404,
    )
    allowed = _precheck(ctx, task_id, int(submission["id"]), ctx.publisher)
    assert allowed["submission_id"] == int(submission["id"]), "发布者可预审成员成果"

    other_task = _create_task(
        ctx,
        "预审权限-其他任务",
        activity_id=activity_id,
        claim_type="assign",
        assignee_id=ctx.ids["worker2"],
    )
    _err(
        ctx.client,
        "POST",
        f"/api/tasks/{int(other_task['id'])}/submissions/{int(submission['id'])}/precheck",
        code=ERR_NOT_FOUND,
        headers=ctx.publisher,
        label="跨任务预审",
        status=404,
    )


# --------------------------------------------------------------------------- #
# 8. 旧稿不能批准新稿
# --------------------------------------------------------------------------- #
def test_old_submission_cannot_approve_new_one(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "旧稿-活动")
    task = _create_task(
        ctx,
        "旧稿-任务",
        activity_id=activity_id,
        deadline="2026-12-30 18:00",
        credit_reward=6,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker, body={"content": "开始"})
    _submit(ctx, task_id, ctx.worker, content="第一版：2026-12-31 18:00")
    first = _submissions(ctx, task_id, ctx.worker)[0]

    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        headers=ctx.publisher,
        body={"pass": False, "reason": "时间写错，请修改", "user_id": ctx.ids["worker"], "submission_id": int(first["id"])},
        label="退回第一版",
    )
    _submit(ctx, task_id, ctx.worker, content="第二版：2026-12-30 18:00")
    rows = _submissions(ctx, task_id, ctx.worker)
    second = max(rows, key=lambda item: item["version"])
    assert second["version"] == 2 and second["latest"] is True, f"第二次提交应生成最新 v2（实际 {rows}）"

    _err(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        code=ERR_CONFLICT,
        headers=ctx.publisher,
        body={"pass": True, "user_id": ctx.ids["worker"], "submission_id": int(first["id"])},
        label="用旧版本批准新稿",
    )
    detail = _ok(ctx.client, "GET", f"/api/tasks/{task_id}", headers=ctx.publisher, label="旧稿拒绝后任务状态")
    member = next(item for item in detail["members"] if item["user_id"] == ctx.ids["worker"])
    assert member["status"] == "submitted", "旧版本验收失败后成员仍应待验收"
    with SessionLocal() as db:
        assert (
            db.query(CreditLog).filter(CreditLog.user_id == ctx.ids["worker"], CreditLog.task_id == task_id).count() == 0
        ), "旧版本验收失败不得加分"

    approved = _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        headers=ctx.publisher,
        body={"pass": True, "user_id": ctx.ids["worker"], "submission_id": int(second["id"])},
        label="验收最新版本",
    )
    assert approved["credited_user_ids"] == [ctx.ids["worker"]], "最新版本验收应加分"
    with SessionLocal() as db:
        assert (
            db.query(CreditLog).filter(CreditLog.user_id == ctx.ids["worker"], CreditLog.task_id == task_id).count() == 1
        ), "通过后积分流水只应有一条"

    _err(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        code=ERR_CONFLICT,
        headers=ctx.publisher,
        body={"pass": True, "user_id": ctx.ids["worker"], "submission_id": int(second["id"])},
        label="重复验收",
    )


# --------------------------------------------------------------------------- #
# 9. 要求变化后旧预审标记 stale
# --------------------------------------------------------------------------- #
def test_precheck_marked_stale_after_requirement_change(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "过期预审-活动")
    task = _create_task(
        ctx,
        "过期预审-任务",
        activity_id=activity_id,
        deadline="2027-01-10 18:00",
        description="初稿必须包含时间",
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker, body={"content": "开始"})
    _submit(ctx, task_id, ctx.worker, content="初稿：2027-01-10 18:00")
    submission = _submissions(ctx, task_id, ctx.worker)[0]
    before = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)
    assert before["verdict"] in {"pass", "unknown"}, f"初始预审应完成（实际 {before['verdict']}）"

    _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"deadline": "2027-01-12 18:00"},
        label="修改任务要求",
    )
    rows = _submissions(ctx, task_id, ctx.worker)
    summary = rows[0]["precheck"]
    assert summary is not None and summary["stale"] is True, (
        f"任务要求变化后旧预审应标记 stale（实际 {summary}）"
    )

# --------------------------------------------------------------------------- #
# 10. 任务资料与仅组织资料的可见性（覆盖 visible_resource_filter 三条分支）
# --------------------------------------------------------------------------- #
def test_task_and_org_only_resource_visibility(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "资料分支-活动")
    task = _create_task(
        ctx,
        "资料分支-任务",
        activity_id=activity_id,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])

    task_resource = _resource(
        ctx,
        ctx.publisher,
        title="资料分支-任务附件",
        summary="只属于本任务成员",
        task_id=task_id,
        url="https://example.com/task-resource",
    )
    worker_items = _ok(
        ctx.client,
        "GET",
        f"/api/resources?task_id={task_id}",
        headers=ctx.worker,
        label="任务成员读取任务资料",
    )["items"]
    assert task_resource["id"] in {item["id"] for item in worker_items}, "任务成员应看到任务资料"

    outsider_items = _ok(
        ctx.client,
        "GET",
        f"/api/resources?task_id={task_id}",
        headers=ctx.outsider,
        label="无关用户读取任务资料",
    )["items"]
    assert task_resource["id"] not in {item["id"] for item in outsider_items}, "任务不可见时资料不得出现"

    org_resource = _resource(
        ctx,
        ctx.publisher,
        title="资料分支-组织通用",
        summary="全组织可见的通用资料",
        org_id=ctx.org_id,
        url="https://example.com/org-resource",
    )
    member_items = _ok(
        ctx.client,
        "GET",
        f"/api/resources?q={org_resource['title']}",
        headers=ctx.worker,
        label="组织成员读取仅组织资料",
    )["items"]
    assert org_resource["id"] in {item["id"] for item in member_items}, "同组织成员应看到仅组织资料"
    outsider_items = _ok(
        ctx.client,
        "GET",
        f"/api/resources?q={org_resource['title']}",
        headers=ctx.outsider,
        label="外组织读取仅组织资料",
    )["items"]
    assert org_resource["id"] not in {item["id"] for item in outsider_items}, "跨组织不得看到仅组织资料"

    # 仅组织资料由本人创建：即使随后失去组织关系，仍按 created_by 可见（设计明确允许）
    creator_id = _ensure_user("aiw04_orgonly", "仅组织资料作者", role="publisher")
    _ensure_org(
        "AIW04 资料审核组织",
        "aiw04-resource-review",
        roles={creator_id: "admin"},
    )
    creator_headers = _login(ctx.client, "aiw04_orgonly")
    own_resource = _resource(
        ctx,
        creator_headers,
        title="资料分支-创建者留存",
        summary="失去组织关系后仍由创建者本人可见",
        org_id=ctx.org_id,
        url="https://example.com/creator-resource",
    )
    with SessionLocal() as db:
        db.query(OrgMember).filter(
            OrgMember.org_id == ctx.org_id, OrgMember.user_id == creator_id
        ).delete()
        db.commit()
    still_visible = _ok(
        ctx.client,
        "GET",
        f"/api/resources?q={own_resource['title']}",
        headers=creator_headers,
        label="创建者失去组织关系后读取自己的资料",
    )["items"]
    assert own_resource["id"] in {item["id"] for item in still_visible}, (
        "仅组织资料应保留创建者访问（created_by 回退）"
    )
    with SessionLocal() as db:
        db.add(OrgMember(org_id=ctx.org_id, user_id=creator_id, role="admin", status="active"))
        db.commit()


# --------------------------------------------------------------------------- #
# 11. 非 http/https 链接：资料拒绝创建、成果预审 fail
# --------------------------------------------------------------------------- #
def test_unsafe_links_are_rejected_or_fail_precheck(ctx: _Ctx) -> None:
    _err(
        ctx.client,
        "POST",
        "/api/resources",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={
            "title": "不安全链接",
            "url": "javascript:alert(1)",
            "activity_id": _create_activity(ctx, "不安全链接-活动"),
        },
        label="资料创建拒绝 javascript 链接",
    )

    activity_id = _create_activity(ctx, "不安全链接-任务活动")
    task = _create_task(
        ctx,
        "不安全链接-任务",
        activity_id=activity_id,
        deadline="2027-02-01 18:00",
        description="必须提供可访问链接",
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker, body={"content": "开始"})
    _submit(
        ctx,
        task_id,
        ctx.worker,
        content="成果时间 2027-02-01 18:00",
        resource_url="javascript:alert(1)",
    )
    submission = _submissions(ctx, task_id, ctx.worker)[0]
    result = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)
    link_check = next(item for item in result["checks"] if item["key"] == "resource_link")
    assert link_check["status"] == "fail", f"非法成果链接应 fail（实际 {link_check}）"
    assert result["verdict"] == "fail", "非法链接不得显示为预审通过"


# --------------------------------------------------------------------------- #
# 12. 模型失败保留规则结论，不冒充通过
# --------------------------------------------------------------------------- #
def test_precheck_ai_failure_keeps_rule_verdict(ctx: _Ctx, monkeypatch) -> None:
    from app.agents import llm_client

    activity_id = _create_activity(ctx, "模型失败-活动")
    task = _create_task(
        ctx,
        "模型失败-任务",
        activity_id=activity_id,
        deadline="2027-03-01 18:00",
        description="写清楚活动时间",
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker, body={"content": "开始"})
    _submit(ctx, task_id, ctx.worker, content="活动时间写成 2027-03-02 18:00，与要求不符。")
    submission = _submissions(ctx, task_id, ctx.worker)[0]

    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)

    def _boom(*_args, **_kwargs):
        raise llm_client.LLMError(llm_client.CODE_API_ERROR, "模拟模型失败")

    monkeypatch.setattr(llm_client, "chat_json", _boom)
    result = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)

    assert result["mock"] is False, "真实模型路径应标记 mock=false"
    assert result["ai_error"], "模型失败必须写 ai_error"
    assert result["verdict"] == "fail", "规则发现错时间时应保持 fail，不得被模型失败覆盖"
    assert _time_check(result)["status"] == "fail", "规则时间检查结论应保留"
    detail = _ok(ctx.client, "GET", f"/api/tasks/{task_id}", headers=ctx.publisher, label="模型失败后任务状态")
    assert detail["status"] == "submitted", "模型失败不得改变任务状态"


# --------------------------------------------------------------------------- #
# 13. 空成果版本预审 fail
# --------------------------------------------------------------------------- #
def test_empty_submission_precheck_fails(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "空成果-活动")
    task = _create_task(
        ctx,
        "空成果-任务",
        activity_id=activity_id,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker, body={"content": "开始"})
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/submit", headers=ctx.worker, label="空成果提交")
    submission = _submissions(ctx, task_id, ctx.worker)[0]
    assert submission["content"] is None and submission["resource_url"] is None

    result = _precheck(ctx, task_id, int(submission["id"]), ctx.worker)
    content_check = next(item for item in result["checks"] if item["key"] == "content_present")
    assert content_check["status"] == "fail", f"空成果应 fail（实际 {content_check}）"
    assert result["verdict"] == "fail", "空成果不得显示为预审通过"

# --------------------------------------------------------------------------- #
# 14. assignee 不能验收他人成果（成果审核与任务管理权限分离）
# --------------------------------------------------------------------------- #
def test_assignee_cannot_verify_other_member(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "验收权限-活动")
    task = _create_task(
        ctx,
        "验收权限-任务",
        activity_id=activity_id,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    task_id = int(task["id"])
    _assign(ctx, task_id, ctx.ids["worker2"])
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", headers=ctx.worker2, body={"content": "开始"})
    _submit(ctx, task_id, ctx.worker2, content="成员二成果")
    submission = _submissions(ctx, task_id, ctx.worker2)[0]

    _err(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        code=ERR_FORBIDDEN,
        headers=ctx.worker,
        body={"pass": True, "user_id": ctx.ids["worker2"], "submission_id": int(submission["id"])},
        label="assignee 验收他人成果",
        status=403,
    )
    detail = _ok(ctx.client, "GET", f"/api/tasks/{task_id}", headers=ctx.publisher, label="越权验收后任务状态")
    member2 = next(item for item in detail["members"] if item["user_id"] == ctx.ids["worker2"])
    assert member2["status"] == "submitted", "越权验收不得改变成员状态"
    with SessionLocal() as db:
        assert (
            db.query(CreditLog)
            .filter(CreditLog.user_id == ctx.ids["worker2"], CreditLog.task_id == task_id)
            .count()
            == 0
        ), "越权验收不得加分"


# --------------------------------------------------------------------------- #
# 15. 非 owner 的活动组织管理员可见活动级资料（活动可见性 admin 分支）
# --------------------------------------------------------------------------- #
def test_activity_admin_branch_visibility(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "资料管理员分支-无任务活动")
    resource = _resource(
        ctx,
        ctx.owner,
        title="资料管理员分支-活动资料",
        summary="活动负责人创建，组织管理员可见",
        activity_id=activity_id,
        url="https://example.com/admin-branch",
    )
    admin_view = _ok(
        ctx.client,
        "GET",
        f"/api/resources?activity_id={activity_id}",
        headers=ctx.publisher,
        label="组织管理员读取无任务活动资料",
    )["items"]
    assert resource["id"] in {item["id"] for item in admin_view}, "非 owner 的组织管理员应可见活动资料"

    worker_view = _ok(
        ctx.client,
        "GET",
        f"/api/resources?activity_id={activity_id}",
        headers=ctx.worker,
        label="普通成员读取无任务活动资料",
    )["items"]
    assert resource["id"] not in {item["id"] for item in worker_view}, "普通成员不得看到不可见活动的资料"