#!/usr/bin/env python
"""AIW-08 「我发布的活动」范围行为测试（契约 `C-NAV-SCOPE@2`）。

覆盖真实 HTTP 行为：

1. ``scope=published`` 只返回 ``owner_id`` 为当前用户的活动中，本人可见的部分；
2. 同组织另一位管理员在大厅（``all``）能看到别人发布的活动，但 ``published`` 不含它；
3. ``published`` 是 ``mine`` 的子集，不是组织范围或前端过滤结果；
4. 普通成员没有发布活动时为空白结果，不报错；
5. 跨组织活动不出现；
6. 新建活动立即出现在发布者的 ``published`` 中，且 ``owner_id`` 为发布者本人；
7. 未登录访问被拒（401 / code 4010），非法 scope 值由契约校验拒绝。

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

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw08-nav-"))
_TEST_DB_PATH = _TMP_DIR / "aiw08_nav.db"

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
    admin2: dict[str, str]
    member: dict[str, str]
    outsider: dict[str, str]
    org_a: int
    org_b: int
    activity_a1: int
    activity_a2: int
    activity_a3: int
    activity_b1: int


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


def _create_activity(
    client: TestClient, headers: dict[str, str], org_id: int, title: str
) -> dict[str, Any]:
    return _ok(
        client,
        "POST",
        "/api/activities",
        headers=headers,
        body={"title": title, "org_id": org_id},
        label=f"创建活动「{title}」",
    )


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
        admin_id = _ensure_user("aiw08_admin", "组织 A 管理员甲")
        admin2_id = _ensure_user("aiw08_admin2", "组织 A 管理员乙")
        member_id = _ensure_user("aiw08_member", "组织 A 成员")
        outsider_id = _ensure_user("aiw08_outsider", "组织 B 管理员")

        org_a = _ensure_org(
            "AIW08 组织 A",
            "aiw08-org-a",
            roles={admin_id: "admin", admin2_id: "admin", member_id: "member"},
        )
        org_b = _ensure_org("AIW08 组织 B", "aiw08-org-b", roles={outsider_id: "admin"})

        admin = _login(client, "aiw08_admin")
        admin2 = _login(client, "aiw08_admin2")
        member = _login(client, "aiw08_member")
        outsider = _login(client, "aiw08_outsider")

        activity_a1 = int(_create_activity(client, admin, org_a, "A1 甲发布")["id"])
        activity_a2 = int(_create_activity(client, admin, org_a, "A2 甲发布")["id"])
        activity_a3 = int(_create_activity(client, admin2, org_a, "A3 乙发布")["id"])
        activity_b1 = int(_create_activity(client, outsider, org_b, "B1 其他组织")["id"])

        yield _Ctx(
            client=client,
            admin=admin,
            admin2=admin2,
            member=member,
            outsider=outsider,
            org_a=org_a,
            org_b=org_b,
            activity_a1=activity_a1,
            activity_a2=activity_a2,
            activity_a3=activity_a3,
            activity_b1=activity_b1,
        )


def test_published_scope_only_returns_own_activities(ctx: _Ctx) -> None:
    assert _activity_ids(ctx.client, ctx.admin, "published") == {ctx.activity_a1, ctx.activity_a2}
    assert _activity_ids(ctx.client, ctx.admin2, "published") == {ctx.activity_a3}


def test_org_admin_all_scope_keeps_others_but_published_does_not(ctx: _Ctx) -> None:
    all_ids = _activity_ids(ctx.client, ctx.admin2, "all")
    assert {ctx.activity_a1, ctx.activity_a2, ctx.activity_a3} <= all_ids, (
        "同组织管理员在大厅应能看到本组织其他负责人发布的活动"
    )
    assert ctx.activity_a1 not in _activity_ids(ctx.client, ctx.admin2, "published"), (
        "大厅可见不等于本人发布；published 不能退化成组织范围"
    )


def test_published_scope_is_subset_of_mine(ctx: _Ctx) -> None:
    published = _activity_ids(ctx.client, ctx.admin, "published")
    mine = _activity_ids(ctx.client, ctx.admin, "mine")
    assert published <= mine, "本人发布的活动必须同时属于「我的活动」"


def test_member_without_published_activity_gets_empty_list(ctx: _Ctx) -> None:
    assert _activity_ids(ctx.client, ctx.member, "published") == set()


def test_published_scope_is_org_isolated(ctx: _Ctx) -> None:
    outsider_published = _activity_ids(ctx.client, ctx.outsider, "published")
    assert outsider_published == {ctx.activity_b1}
    assert ctx.activity_a1 not in outsider_published, "跨组织活动不得出现在 published"


def test_new_activity_appears_in_publisher_scope_immediately(ctx: _Ctx) -> None:
    created = _create_activity(ctx.client, ctx.admin, ctx.org_a, "A4 甲新发布")
    new_id = int(created["id"])
    with SessionLocal() as db:
        admin_id = int(db.query(User).filter(User.username == "aiw08_admin").one().id)
    assert int(created["owner_id"]) == admin_id, "活动 owner_id 必须是发布者本人"
    assert new_id in _activity_ids(ctx.client, ctx.admin, "published")
    assert new_id not in _activity_ids(ctx.client, ctx.admin2, "published")


def test_published_scope_requires_login(ctx: _Ctx) -> None:
    status, payload = _payload(ctx.client, "GET", "/api/activities?scope=published")
    assert status in {401, 403}, f"未登录访问应被拒，实际 HTTP {status}"
    assert payload.get("code") == 4010


def test_unknown_scope_value_is_rejected(ctx: _Ctx) -> None:
    # 项目统一口径：参数校验失败返回 HTTP 200 + code=4001（见 main 的 RequestValidationError 处理）
    status, payload = _payload(ctx.client, "GET", "/api/activities?scope=bogus", headers=ctx.admin)
    assert status == 200, f"参数校验失败仍走统一响应口径，实际 HTTP {status}"
    assert payload.get("code") == 4001, f"非法 scope 应被契约校验拒绝，实际 code={payload.get('code')}"