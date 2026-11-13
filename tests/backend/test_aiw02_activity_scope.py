#!/usr/bin/env python
"""AIW-02 活动范围行为测试（契约 `C-ACT-SCOPE@1`）。

覆盖真实 HTTP 行为：

1. ``scope=all`` 保持既有可见范围；
2. ``scope=mine`` 只返回我是负责人、或活动下存在我参与/管理任务的活动；
3. 活动负责人即使活动下没有任务也在 ``mine`` 中；
4. approved 报名成员命中；只有 pending 报名不命中；
5. 发布者（协作者）命中；
6. 组织内无关成员不命中；其他组织活动不出现，详情 4040；
7. ``GET /api/tasks?scope=mine`` 与活动范围共用同一「我的任务」条件，不含 pending；
8. 未登录 401/4010。

隔离性：导入 ``app`` 前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立 SQLite，
关闭调度器并强制 ``MAAS_MOCK=1``；不触碰 ``backend/campus.db``。
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

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw02-scope-"))
_TEST_DB_PATH = _TMP_DIR / "aiw02_scope.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import OrgMember, Organization, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

PASSWORD = "TestPass123!"


@dataclass
class _Ctx:
    client: TestClient
    admin: dict[str, str]
    member1: dict[str, str]
    member2: dict[str, str]
    collab: dict[str, str]
    outsider: dict[str, str]
    org_a: int
    org_b: int
    activity_a1: int
    activity_a2: int
    activity_b1: int
    task_member1: int
    task_pending: int
    task_collab: int
    task_org_b: int


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
        payload = response.json()
    except ValueError:  # pragma: no cover - 非 JSON 响应说明发生未捕获异常
        raise AssertionError(f"{method} {path}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert isinstance(payload, dict), f"{method} {path}：响应体不是对象"
    return response.status_code, payload


def _ok(
    client: TestClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    label: str = "",
) -> dict:
    status, payload = _payload(client, method, path, headers=headers, body=body)
    assert status == 200, f"{label}：期望 HTTP 200，实际 HTTP {status}（{payload.get('msg')}）"
    assert payload.get("code") == 0, f"{label}：期望 code=0，实际 {payload.get('code')}（{payload.get('msg')}）"
    data = payload.get("data")
    assert isinstance(data, dict), f"{label}：data 不是对象"
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
    return {"Cookie": f"{SESSION_COOKIE}={session}; {CSRF_COOKIE}={csrf}", CSRF_HEADER: csrf}


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    payload = response.json()
    assert response.status_code == 200 and payload.get("code") == 0, f"登录 {username} 失败"
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
        for user_id, role in roles.items():
            row = (
                db.query(OrgMember)
                .filter(OrgMember.org_id == int(org.id), OrgMember.user_id == int(user_id))
                .first()
            )
            if row is None:
                db.add(OrgMember(org_id=int(org.id), user_id=int(user_id), role=role, status="active"))
            else:
                row.role = role
                row.status = "active"
        db.commit()
        db.refresh(org)
        return int(org.id)


def _create_activity(client: TestClient, headers: dict[str, str], org_id: int, title: str) -> int:
    data = _ok(
        client,
        "POST",
        "/api/activities",
        headers=headers,
        body={"title": title, "org_id": org_id},
        label=f"创建活动「{title}」",
    )
    return int(data["id"])


def _create_task(
    client: TestClient,
    headers: dict[str, str],
    *,
    org_id: int,
    title: str,
    activity_id: int | None = None,
) -> int:
    body: dict[str, Any] = {"title": title, "org_id": org_id, "claim_type": "open"}
    if activity_id is not None:
        body["activity_id"] = activity_id
    data = _ok(
        client,
        "POST",
        "/api/tasks",
        headers=headers,
        body=body,
        label=f"发布任务「{title}」",
    )
    return int(data["id"])


def _activity_ids(client: TestClient, headers: dict[str, str], scope: str) -> set[int]:
    data = _ok(
        client,
        "GET",
        f"/api/activities?scope={scope}",
        headers=headers,
        label=f"活动列表 scope={scope}",
    )
    return {int(item["id"]) for item in data["items"]}


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        admin_id = _ensure_user("aiw02_admin", "组织 A 管理员")
        member1_id = _ensure_user("aiw02_member1", "参与成员")
        member2_id = _ensure_user("aiw02_member2", "无关成员")
        collab_id = _ensure_user("aiw02_collab", "协作者")
        outsider_id = _ensure_user("aiw02_outsider", "组织 B 管理员")

        org_a = _ensure_org(
            "AIW02 组织 A",
            "aiw02-org-a",
            roles={admin_id: "admin", member1_id: "member", member2_id: "member", collab_id: "collaborator"},
        )
        org_b = _ensure_org("AIW02 组织 B", "aiw02-org-b", roles={outsider_id: "admin"})

        admin = _login(client, "aiw02_admin")
        member1 = _login(client, "aiw02_member1")
        member2 = _login(client, "aiw02_member2")
        collab = _login(client, "aiw02_collab")
        outsider = _login(client, "aiw02_outsider")

        activity_a1 = _create_activity(client, admin, org_a, "A1 有参与成员")
        activity_a2 = _create_activity(client, admin, org_a, "A2 待审批与协作者")
        activity_b1 = _create_activity(client, outsider, org_b, "B1 其他组织")

        task_member1 = _create_task(
            client, admin, org_id=org_a, title="A1 成员执行任务", activity_id=activity_a1
        )
        task_pending = _create_task(
            client, admin, org_id=org_a, title="A2 仅待审批任务", activity_id=activity_a2
        )
        task_collab = _create_task(
            client, collab, org_id=org_a, title="A2 协作者发布任务", activity_id=activity_a2
        )
        task_org_b = _create_task(
            client, outsider, org_id=org_b, title="B1 组织 B 任务", activity_id=activity_b1
        )

        # member1 对 A1 任务报名并通过；对 A2 任务只保留 pending
        applied = _ok(
            client,
            "POST",
            f"/api/tasks/{task_member1}/apply",
            headers=member1,
            label="member1 报名 A1 任务",
        )
        _ok(
            client,
            "POST",
            f"/api/applications/{int(applied['application']['id'])}/decide",
            headers=admin,
            body={"approve": True},
            label="审批通过 A1 报名",
        )
        _ok(
            client,
            "POST",
            f"/api/tasks/{task_pending}/apply",
            headers=member1,
            label="member1 报名 A2 任务（保持 pending）",
        )

        yield _Ctx(
            client=client,
            admin=admin,
            member1=member1,
            member2=member2,
            collab=collab,
            outsider=outsider,
            org_a=org_a,
            org_b=org_b,
            activity_a1=activity_a1,
            activity_a2=activity_a2,
            activity_b1=activity_b1,
            task_member1=task_member1,
            task_pending=task_pending,
            task_collab=task_collab,
            task_org_b=task_org_b,
        )


def test_all_scope_keeps_existing_visibility(ctx: _Ctx) -> None:
    admin_ids = _activity_ids(ctx.client, ctx.admin, "all")
    assert {ctx.activity_a1, ctx.activity_a2} <= admin_ids, "组织管理员应看到本组织活动"
    assert ctx.activity_b1 not in admin_ids, "组织管理员不得看到其他组织活动"

    member_ids = _activity_ids(ctx.client, ctx.member1, "all")
    assert ctx.activity_a1 in member_ids and ctx.activity_a2 in member_ids
    assert ctx.activity_b1 not in member_ids, "成员不得看到其他组织活动"

    outsider_ids = _activity_ids(ctx.client, ctx.outsider, "all")
    assert outsider_ids == {ctx.activity_b1}, "组织 B 管理员只应看到 B1"


def test_mine_scope_for_owner_and_participant(ctx: _Ctx) -> None:
    admin_ids = _activity_ids(ctx.client, ctx.admin, "mine")
    assert admin_ids == {ctx.activity_a1, ctx.activity_a2}, "活动负责人应精确命中其两个活动"
    assert ctx.activity_b1 not in admin_ids

    member_ids = _activity_ids(ctx.client, ctx.member1, "mine")
    assert member_ids == {ctx.activity_a1}, "approved 参与只命中 A1；pending 不命中 A2"
    assert ctx.activity_a2 not in member_ids, "只有 pending 报名不能算我的活动"


def test_mine_scope_for_unrelated_member_and_publisher(ctx: _Ctx) -> None:
    unrelated = _activity_ids(ctx.client, ctx.member2, "mine")
    assert unrelated == set(), "组织内无关成员不应因可见性获得任何我的活动"

    collab_ids = _activity_ids(ctx.client, ctx.collab, "mine")
    assert collab_ids == {ctx.activity_a2}, "协作者只应命中自己发布任务所属的活动"

    outsider_ids = _activity_ids(ctx.client, ctx.outsider, "mine")
    assert outsider_ids == {ctx.activity_b1}, "其他组织管理员只应命中自己的活动"


def test_task_scope_mine_is_consistent(ctx: _Ctx) -> None:
    data = _ok(
        ctx.client,
        "GET",
        "/api/tasks?scope=mine",
        headers=ctx.member1,
        label="member1 我的任务",
    )
    ids = {int(item["id"]) for item in data["items"]}
    assert ctx.task_member1 in ids, "approved 成员任务应在我的任务中"
    assert ctx.task_pending not in ids, "pending 报名不应算我的任务"
    assert ctx.task_collab not in ids, "他人发布任务不应算我的任务"
    assert ctx.task_org_b not in ids, "其他组织任务不得出现"


def test_cross_org_activity_detail_is_hidden(ctx: _Ctx) -> None:
    status, payload = _payload(
        ctx.client,
        "GET",
        f"/api/activities/{ctx.activity_b1}",
        headers=ctx.admin,
    )
    assert status == 404, f"跨组织活动详情应 404，实际 HTTP {status}"
    assert payload.get("code") == 4040


def test_unauthenticated_activity_list_rejected(ctx: _Ctx) -> None:
    status, payload = _payload(ctx.client, "GET", "/api/activities?scope=mine")
    assert status == 401, f"未登录应 401，实际 {status}"
    assert payload.get("code") == 4010