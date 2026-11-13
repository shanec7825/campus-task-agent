#!/usr/bin/env python
"""阶段 18 活动负责人任务可见性后端行为测试（契约 `C-AUTHZ-VISIBILITY@1`）。

覆盖范围（全部通过真实 HTTP 行为验证，不做字符串 / 源码检查）：

1. 任务详情：活动负责人（既非任务发布者 / 成员 / 报名者，也不是任务所属组织的
   ``admin``）可以读取其活动下由他人发布的任务详情（200 + 任务载荷）；
2. 任务列表：同一负责人的 ``GET /api/tasks?activity_id=`` 结果包含他人发布的任务；
3. 活动树：负责人读取活动详情时，``tasks`` 包含他人发布的第一层任务及其子任务；
4. 验收可达：负责人验收其活动下他人发布的任务成功（``verified``）；未提交时返回
   4090，而不是 4040；
5. 无关用户：与活动无 publisher / assignee / 成员 / 报名 / 组织成员关系的普通用户
   读取该任务仍返回 4040「任务不存在」；
6. 不扩散：``activity_id IS NULL`` 的独立任务不因负责人身份获得可见性（仍 4040）；
7. 无组织活动的发布授权（R4）：非活动负责人向 ``org_id IS NULL`` 的活动创建任务、
   把既有任务移入他人的无组织活动均返回 4030「无权在该活动下创建事务」且不写库；
   负责人本人向自己的无组织活动创建任务正常落库。

隔离性：在导入 ``app`` 之前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立
SQLite 文件，关闭调度器并强制 ``MAAS_MOCK=1``；不触碰 ``backend/campus.db``。

认证（`C-SESSION@1`）：fixture 直接写库准备账号（``password_hash``、
``status='active'``）与组织关系，再 ``POST /api/auth/login``；从 ``Set-Cookie``
提取 ``cta_session`` / ``cta_csrf`` 组装显式 ``Cookie`` 与 ``X-CSRF-Token``，
以便同一测试同时持有多身份。

可独立运行：``pytest tests/backend/test_activity_workflow.py``。
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

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-activity-workflow-"))
_TEST_DB_PATH = _TMP_DIR / "activity_workflow.db"

# 必须在导入 app 之前完成：app.db 在模块导入时按 DATABASE_PATH 创建引擎。
os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Activity, OrgMember, Organization, Task, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

ERR_CONFLICT = 4090
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040

#: 测试账号的固定密码；fixture 直接写 ``password_hash`` 与 ``status='active'``。
PASSWORD = "TestPass123!"


@dataclass
class _Ctx:
    client: TestClient
    owner: dict[str, str]
    publisher: dict[str, str]
    worker: dict[str, str]
    outsider: dict[str, str]
    ids: dict[str, int]
    org_id: int


# --------------------------------------------------------------------------- #
# HTTP 工具（Cookie 会话 + 双提交 CSRF；不依赖共享 client 的 cookie jar）
# --------------------------------------------------------------------------- #
def _request(
    client: TestClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
):
    return client.request(method, path, json=body, headers=headers or {})


def _payload(
    client: TestClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    label: str = "",
) -> dict:
    response = _request(client, method, path, headers=headers, body=body)
    try:
        payload = response.json()
    except ValueError:  # 响应非 JSON（例如未捕获 500）
        raise AssertionError(f"{label}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert isinstance(payload, dict), f"{label}：响应体不是对象（HTTP {response.status_code}）"
    return payload


def _ok(
    client: TestClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    label: str = "",
) -> dict:
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
    headers: dict[str, str] | None = None,
    body: Any = None,
    label: str = "",
    status: int = 200,
) -> dict:
    response = _request(client, method, path, headers=headers, body=body)
    payload = response.json()
    assert payload.get("code") == code, (
        f"{label}：期望 code={code}，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    assert response.status_code == status, f"{label}：期望 HTTP {status}，实际 HTTP {response.status_code}"
    return payload


def _session_headers(response) -> dict[str, str]:
    """从登录响应的 ``Set-Cookie`` 提取会话与 CSRF，组装可直接复用的请求头。"""
    values: dict[str, str] = {}
    for raw in response.headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        if name.strip() in {SESSION_COOKIE, CSRF_COOKIE}:
            values[name.strip()] = rest.split(";", 1)[0].strip()

    session = values.get(SESSION_COOKIE)
    csrf = values.get(CSRF_COOKIE)
    assert session and csrf, (
        f"登录响应缺少会话 Cookie（set-cookie={response.headers.get_list('set-cookie')}）"
    )
    return {
        "Cookie": f"{SESSION_COOKIE}={session}; {CSRF_COOKIE}={csrf}",
        CSRF_HEADER: csrf,
    }


def _login(client: TestClient, username: str, password: str = PASSWORD) -> tuple[dict[str, str], dict]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    payload = response.json()
    assert response.status_code == 200 and payload.get("code") == 0, (
        f"登录 {username}：期望 HTTP 200 + code=0，实际 HTTP {response.status_code} "
        f"+ code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    headers = _session_headers(response)
    # 不依赖共享 client 的 cookie jar：本文件需要同时持有多个身份。
    client.cookies.clear()
    data = payload.get("data")
    assert isinstance(data, dict) and isinstance(data.get("user"), dict), "登录响应缺少 data.user"
    return headers, data["user"]


def _ensure_user(username: str, display_name: str, *, role: str) -> int:
    """直接写库准备可登录账号：必须带 ``password_hash`` 且 ``status='active'``。"""
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
    """直接写库准备组织与成员角色（``user_id -> role``）。"""
    with SessionLocal() as db:
        org = db.query(Organization).filter(Organization.slug == slug).first()
        if org is None:
            org = Organization(name=name, slug=slug, status="active")
            db.add(org)
            db.flush()

        memberships = {
            int(row.user_id): row
            for row in db.query(OrgMember).filter(OrgMember.org_id == int(org.id)).all()
        }
        for user_id, role in roles.items():
            row = memberships.get(int(user_id))
            if row is None:
                db.add(
                    OrgMember(
                        org_id=int(org.id),
                        user_id=int(user_id),
                        role=role,
                        status="active",
                    )
                )
            else:
                row.role = role
                row.status = "active"

        db.commit()
        db.refresh(org)
        return int(org.id)


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        owner_id = _ensure_user("owner01", "赵负责人", role="publisher")
        publisher_id = _ensure_user("publisher01", "钱发布者", role="publisher")
        worker_id = _ensure_user("worker01", "孙执行者", role="student")
        outsider_id = _ensure_user("outsider01", "周路人", role="student")

        # 负责人只有 collaborator（不是 admin）：任务所属组织的 admin 是发布者。
        org_id = _ensure_org(
            "阶段 18 活动负责人测试组织",
            "phase18-activity-owner",
            roles={owner_id: "collaborator", publisher_id: "admin", worker_id: "member"},
        )
        # 无关用户属于另一个组织，与活动及其任务没有任何关系。
        _ensure_org(
            "阶段 18 无关用户组织",
            "phase18-outsider",
            roles={outsider_id: "member"},
        )

        owner_headers, owner_user = _login(client, "owner01")
        publisher_headers, publisher_user = _login(client, "publisher01")
        worker_headers, _ = _login(client, "worker01")
        outsider_headers, _ = _login(client, "outsider01")

        assert int(owner_user["id"]) == owner_id, "owner01 登录用户应为种子用户"
        assert int(publisher_user["id"]) == publisher_id, "publisher01 登录用户应为种子用户"

        yield _Ctx(
            client=client,
            owner=owner_headers,
            publisher=publisher_headers,
            worker=worker_headers,
            outsider=outsider_headers,
            ids={
                "owner01": owner_id,
                "publisher01": publisher_id,
                "worker01": worker_id,
                "outsider01": outsider_id,
            },
            org_id=org_id,
        )


# --------------------------------------------------------------------------- #
# 业务辅助
# --------------------------------------------------------------------------- #
def _create_activity(ctx: _Ctx, title: str) -> dict:
    return _ok(
        ctx.client,
        "POST",
        "/api/activities",
        headers=ctx.owner,
        body={"title": title, "org_id": ctx.org_id},
        label=f"负责人创建活动「{title}」",
    )


def _create_task(ctx: _Ctx, title: str, **fields: Any) -> dict:
    """他人（组织 admin）在负责人的活动下发布任务。"""
    return _ok(
        ctx.client,
        "POST",
        "/api/tasks",
        headers=ctx.publisher,
        body={"title": title, **fields},
        label=f"发布者创建任务「{title}」",
    )


def _activity_task_ids(ctx: _Ctx, activity_id: int) -> set[int]:
    detail = _ok(ctx.client, "GET", f"/api/activities/{activity_id}", headers=ctx.owner, label="负责人读活动详情")
    ids: set[int] = set()
    for node in detail["tasks"]:
        ids.add(int(node["id"]))
        ids.update(int(child["id"]) for child in (node.get("children") or []))
    return ids


def _activity_with_task(ctx: _Ctx, *, title_prefix: str) -> tuple[int, int, int]:
    """活动负责人建活动，发布者建「父任务（已指派成员）+ 子任务」，返回三者 id。"""
    activity_id = int(_create_activity(ctx, f"{title_prefix}-活动")["id"])
    top = _create_task(
        ctx,
        f"{title_prefix}-父任务",
        activity_id=activity_id,
        claim_type="assign",
        assignee_id=ctx.ids["worker01"],
    )
    top_id = int(top["id"])
    sub = _create_task(ctx, f"{title_prefix}-子任务", parent_id=top_id)
    return activity_id, top_id, int(sub["id"])


# --------------------------------------------------------------------------- #
# 1. 负责人可读取他人发布的任务
# --------------------------------------------------------------------------- #
def test_activity_owner_can_view_task_published_by_other(ctx: _Ctx) -> None:
    activity_id, top_id, sub_id = _activity_with_task(ctx, title_prefix="负责人可见-详情")

    detail = _ok(ctx.client, "GET", f"/api/tasks/{top_id}", headers=ctx.owner, label="负责人读他人任务详情")
    assert int(detail["id"]) == top_id, f"应返回目标任务（实际 {detail['id']}）"
    assert int(detail["activity_id"]) == activity_id, f"任务应归属该活动（实际 {detail['activity_id']}）"
    assert int(detail["publisher_id"]) == ctx.ids["publisher01"], "任务发布者应为他人"
    assert detail["activity_title"] == "负责人可见-详情-活动", (
        f"负责人应看到活动标题（实际 {detail.get('activity_title')!r}）"
    )

    sub_detail = _ok(ctx.client, "GET", f"/api/tasks/{sub_id}", headers=ctx.owner, label="负责人读他人子任务详情")
    assert int(sub_detail["parent_id"]) == top_id, "子任务详情应回显父任务"

    listed = _ok(
        ctx.client,
        "GET",
        f"/api/tasks?activity_id={activity_id}&include_sub=true",
        headers=ctx.owner,
        label="负责人按活动筛选任务列表",
    )["items"]
    assert {top_id, sub_id} <= {int(item["id"]) for item in listed}, (
        f"负责人任务列表应包含他人发布的父任务与子任务（实际 {[int(item['id']) for item in listed]}）"
    )


# --------------------------------------------------------------------------- #
# 2. 活动树包含他人发布的任务
# --------------------------------------------------------------------------- #
def test_activity_owner_sees_others_tasks_in_activity_tree(ctx: _Ctx) -> None:
    activity_id, top_id, sub_id = _activity_with_task(ctx, title_prefix="负责人可见-树")

    detail = _ok(ctx.client, "GET", f"/api/activities/{activity_id}", headers=ctx.owner, label="负责人读活动任务树")
    node_ids = [int(node["id"]) for node in detail["tasks"]]
    assert top_id in node_ids, f"活动树应包含他人发布的第一层任务（实际 {node_ids}）"

    top_node = next(node for node in detail["tasks"] if int(node["id"]) == top_id)
    assert [int(child["id"]) for child in top_node["children"]] == [sub_id], (
        f"活动树应挂载他人发布的子任务（实际 {top_node['children']}）"
    )
    assert _activity_task_ids(ctx, activity_id) == {top_id, sub_id}, "活动树应包含全部他人发布的任务"


# --------------------------------------------------------------------------- #
# 3. 负责人验收可达（成功或 4090，不是 4040）
# --------------------------------------------------------------------------- #
def test_activity_owner_can_verify_and_gets_conflict_not_not_found(ctx: _Ctx) -> None:
    activity_id, top_id, sub_id = _activity_with_task(ctx, title_prefix="负责人验收")

    # 未提交的成员：负责人有权验收，业务状态不允许 → 4090
    conflict = _err(
        ctx.client,
        "POST",
        f"/api/tasks/{top_id}/verify",
        code=ERR_CONFLICT,
        headers=ctx.owner,
        body={"pass": True},
        label="负责人验收未提交任务",
    )
    assert conflict.get("msg") != "任务不存在", "负责人的验收不得被可见性前置校验遮蔽为 4040"

    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{top_id}/progress",
        headers=ctx.worker,
        body={"content": "负责人验收流程-执行中"},
        label="成员提交进度",
    )
    _ok(ctx.client, "POST", f"/api/tasks/{top_id}/submit", headers=ctx.worker, label="成员提交完成")

    verified = _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{top_id}/verify",
        headers=ctx.owner,
        body={"pass": True},
        label="负责人验收他人任务",
    )
    assert verified["task"]["status"] == "verified", (
        f"负责人验收后任务应为 verified（实际 {verified['task']['status']}）"
    )

    # 子任务不受影响，仍保持未验收，确认验收只作用于目标任务。
    remain = _ok(ctx.client, "GET", f"/api/tasks/{sub_id}", headers=ctx.owner, label="验收后读子任务")
    assert remain["status"] != "verified", f"子任务状态不应被顺带改写（实际 {remain['status']}）"
    assert int(remain["activity_id"]) == activity_id, "子任务仍属于该活动"


# --------------------------------------------------------------------------- #
# 4. 无关成员仍 4040，且不扩散到独立任务
# --------------------------------------------------------------------------- #
def test_outsider_still_gets_task_not_found(ctx: _Ctx) -> None:
    _activity_id, top_id, sub_id = _activity_with_task(ctx, title_prefix="无关成员")

    for task_id, label in ((top_id, "无关成员读父任务"), (sub_id, "无关成员读子任务")):
        missing = _err(
            ctx.client,
            "GET",
            f"/api/tasks/{task_id}",
            code=ERR_NOT_FOUND,
            headers=ctx.outsider,
            label=label,
            status=404,
        )
        assert missing.get("msg") == "任务不存在", (
            f"{label}应逐字返回「任务不存在」（实际 {missing.get('msg')!r}）"
        )

    listed = _ok(
        ctx.client,
        "GET",
        f"/api/tasks?activity_id={_activity_id}&include_sub=true",
        headers=ctx.outsider,
        label="无关成员按活动筛选任务列表",
    )["items"]
    assert {top_id, sub_id}.isdisjoint({int(item["id"]) for item in listed}), (
        f"无关成员的任务列表不得包含该活动任务（实际 {[int(item['id']) for item in listed]}）"
    )


def test_activity_owner_does_not_see_unrelated_standalone_task(ctx: _Ctx) -> None:
    standalone = _ok(
        ctx.client,
        "POST",
        "/api/tasks",
        headers=ctx.publisher,
        body={"title": "负责人可见-他人独立任务"},
        label="发布者创建独立任务",
    )
    standalone_id = int(standalone["id"])
    assert standalone.get("activity_id") is None, "前置条件：独立任务无活动归属"

    missing = _err(
        ctx.client,
        "GET",
        f"/api/tasks/{standalone_id}",
        code=ERR_NOT_FOUND,
        headers=ctx.owner,
        label="负责人读他人独立任务",
        status=404,
    )
    assert missing.get("msg") == "任务不存在", (
        f"活动负责人身份不得扩散到独立任务（实际 {missing.get('msg')!r}）"
    )

# --------------------------------------------------------------------------- #
# 5. 无组织活动的发布授权（C-ACTIVITY-PUBLISH-AUTH@1）
# --------------------------------------------------------------------------- #
def _create_orgless_activity(ctx: _Ctx, title: str) -> int:
    """活动负责人创建 ``org_id IS NULL`` 的活动。"""
    created = _ok(
        ctx.client,
        "POST",
        "/api/activities",
        headers=ctx.owner,
        body={"title": title},
        label=f"创建无组织活动「{title}」",
    )
    assert created.get("org_id") is None, f"前置条件：活动应无组织归属（实际 {created.get('org_id')}）"
    return int(created["id"])


def test_non_owner_cannot_publish_under_orgless_activity(ctx: _Ctx) -> None:
    activity_id = _create_orgless_activity(ctx, "无组织活动-他人禁止发布")

    rejected = _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_FORBIDDEN,
        headers=ctx.publisher,
        body={"title": "无组织活动-越权任务", "activity_id": activity_id},
        label="非负责人向无组织活动创建任务",
        status=403,
    )
    assert rejected.get("msg") == "无权在该活动下创建事务", (
        f"越权文案应逐字返回（实际 {rejected.get('msg')!r}）"
    )

    # 显式带 org_id 也不能绕过无组织活动的负责人校验。
    _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_FORBIDDEN,
        headers=ctx.publisher,
        body={"title": "无组织活动-带组织越权任务", "activity_id": activity_id, "org_id": ctx.org_id},
        label="非负责人带 org_id 向无组织活动创建任务",
        status=403,
    )

    detail = _ok(ctx.client, "GET", f"/api/activities/{activity_id}", headers=ctx.owner, label="授权失败后读活动详情")
    assert detail["tasks"] == [], f"授权失败不得写入任务（实际 {detail['tasks']}）"


def test_activity_owner_can_publish_under_own_orgless_activity(ctx: _Ctx) -> None:
    activity_id = _create_orgless_activity(ctx, "无组织活动-负责人本人发布")

    created = _ok(
        ctx.client,
        "POST",
        "/api/tasks",
        headers=ctx.owner,
        body={"title": "无组织活动-负责人任务", "activity_id": activity_id},
        label="负责人向自己的无组织活动创建任务",
    )
    assert int(created["activity_id"]) == activity_id, (
        f"任务应落库 activity_id（实际 {created.get('activity_id')}）"
    )
    assert created.get("org_id") is None, f"无组织活动下的任务 org_id 应保持 null（实际 {created.get('org_id')}）"

    detail = _ok(ctx.client, "GET", f"/api/activities/{activity_id}", headers=ctx.owner, label="负责人读自己的无组织活动")
    assert [int(node["id"]) for node in detail["tasks"]] == [int(created["id"])], (
        f"新任务应出现在活动树中（实际 {[int(node['id']) for node in detail['tasks']]}）"
    )


def test_patch_into_others_orgless_activity_forbidden(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        activity = Activity(
            title="无组织活动-移入目标",
            owner_id=ctx.ids["publisher01"],
            org_id=None,
            status="published",
        )
        db.add(activity)
        db.flush()
        activity_id = int(activity.id)
        # 活动下预置一条 worker01 可见的任务：让 PATCH 越过既有「活动不存在」防护，
        # 直达 resolve_task_org 的发布授权校验。
        db.add(
            Task(
                activity_id=activity_id,
                title="无组织活动-既有可见任务",
                status="published",
                publisher_id=ctx.ids["worker01"],
            )
        )
        db.commit()

    own = _ok(
        ctx.client,
        "POST",
        "/api/tasks",
        headers=ctx.worker,
        body={"title": "无组织活动-待移入独立任务"},
        label="创建待移入的独立任务",
    )
    own_id = int(own["id"])
    assert own.get("activity_id") is None, "前置条件：待移入任务无活动归属"

    rejected = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{own_id}",
        code=ERR_FORBIDDEN,
        headers=ctx.worker,
        body={"activity_id": activity_id},
        label="把任务移入他人的无组织活动",
        status=403,
    )
    assert rejected.get("msg") == "无权在该活动下创建事务", (
        f"移入越权文案应逐字返回（实际 {rejected.get('msg')!r}）"
    )

    after = _ok(ctx.client, "GET", f"/api/tasks/{own_id}", headers=ctx.worker, label="移入失败后读任务")
    assert after.get("activity_id") is None, (
        f"授权失败不得改写任务活动归属（实际 {after.get('activity_id')}）"
    )