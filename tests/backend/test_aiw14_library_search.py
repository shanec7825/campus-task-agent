#!/usr/bin/env python
"""AIW-14 r2 Library 私有链接与 mine 搜索行为测试（契约 `C-LIBRARY@1` / `C-MY-SEARCH@1`）。

覆盖范围（全部走真实 HTTP 行为）：

1. Library 链接新增 / 列表 / 更新只作用于当前会话 owner，客户端不能自选 owner；
2. 非本人或不存在统一 ``4040``，非法 scheme / 超长字段 / 空标题统一 ``4001``；
3. 不提供 DELETE，刷新（重建 TestClient）后数据仍在，分页与上限生效；
4. ``/api/search/mine`` 只返回 mine 范围，组织内可见但非 mine 的对象不混入；
5. 标题匹配大小写不敏感，空词返回两个空组，``q`` / ``limit`` 超限返回 ``4001``；
6. 搜索按活动 / 任务分组，任务项与 ``TaskOut`` 字段对齐，不含跨组织他人标题。

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
from urllib.parse import quote

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw14-library-search-"))
_TEST_DB_PATH = _TMP_DIR / "aiw14.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Activity, LibraryLink, OrgMember, Organization, Task, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

PASSWORD = "TestPass123!"
ERR_INVALID_PARAM = 4001
ERR_CSRF = 4030
ERR_NOT_FOUND = 4040


@dataclass
class _Ctx:
    client: TestClient
    alice: dict[str, str]
    bob: dict[str, str]
    org_id: int
    alice_activity: int
    bob_activity: int
    alice_task: int
    bob_tasks: list[int]
    carol_task: int


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
    actual_status, payload = _payload(client, method, path, headers=headers, body=body)
    assert payload.get("code") == code, (
        f"{label}：期望 code={code}，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    assert actual_status == status, f"{label}：期望 HTTP {status}，实际 HTTP {actual_status}"
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


def _seed_activity(title: str, owner_id: int, org_id: int | None) -> int:
    with SessionLocal() as db:
        row = Activity(title=title, owner_id=owner_id, org_id=org_id, status="published")
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)


def _seed_task(title: str, publisher_id: int, org_id: int | None) -> int:
    with SessionLocal() as db:
        row = Task(
            title=title,
            publisher_id=publisher_id,
            org_id=org_id,
            status="published",
            claim_type="open",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)


def _create_link(
    client: TestClient, headers: dict[str, str], title: str, url: str = "https://example.com/a"
) -> dict:
    return _ok(
        client,
        "POST",
        "/api/library/links",
        headers=headers,
        body={"title": title, "url": url, "note": f"{title} 的说明"},
        label=f"新增链接「{title}」",
    )


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        alice_id = _ensure_user("aiw14_alice", "Alice")
        bob_id = _ensure_user("aiw14_bob", "Bob")
        carol_id = _ensure_user("aiw14_carol", "Carol")

        org_id = _ensure_org("AIW14 组织", "aiw14-org", roles={alice_id: "admin", bob_id: "member"})

        alice_activity = _seed_activity("Alpha 迎新活动", alice_id, org_id)
        bob_activity = _seed_activity("Bob Alpha 计划", bob_id, org_id)
        _seed_activity("Alpha 外部活动", carol_id, None)

        alice_task = _seed_task("Alpha 场地布置", alice_id, org_id)
        bob_tasks = [
            _seed_task("alpha 物资采购", bob_id, org_id),
            _seed_task("Alpha 签到表", bob_id, org_id),
            _seed_task("Beta 无关任务", bob_id, org_id),
        ]
        carol_task = _seed_task("Alpha 他人任务", carol_id, None)

        yield _Ctx(
            client=client,
            alice=_login(client, "aiw14_alice"),
            bob=_login(client, "aiw14_bob"),
            org_id=org_id,
            alice_activity=alice_activity,
            bob_activity=bob_activity,
            alice_task=alice_task,
            bob_tasks=bob_tasks,
            carol_task=carol_task,
        )


# --------------------------------------------------------------------------- #
# Library 私有链接
# --------------------------------------------------------------------------- #
def test_create_and_list_own_links(ctx: _Ctx) -> None:
    created = _create_link(ctx.client, ctx.alice, "Alice 参考一", "https://example.com/one")
    assert created["title"] == "Alice 参考一"
    assert created["url"] == "https://example.com/one"
    assert created["note"] == "Alice 参考一 的说明"
    assert created["created_at"] and created["updated_at"]
    assert "owner_id" not in created, "所有者来自会话，不在响应里暴露可写字段"

    data = _ok(ctx.client, "GET", "/api/library/links", headers=ctx.alice, label="Alice 链接列表")
    assert data["total"] >= 1
    assert created["id"] in {int(item["id"]) for item in data["items"]}

    bob_data = _ok(ctx.client, "GET", "/api/library/links", headers=ctx.bob, label="Bob 链接列表")
    assert bob_data["items"] == [] and bob_data["total"] == 0, "个人链接不能跨账号可见"


def test_client_cannot_choose_owner(ctx: _Ctx) -> None:
    bob_id = _ensure_user("aiw14_bob", "Bob")
    created = _ok(
        ctx.client,
        "POST",
        "/api/library/links",
        headers=ctx.alice,
        body={
            "title": "伪造 owner 的链接",
            "url": "https://example.com/owner",
            "owner_id": bob_id,
        },
        label="忽略客户端 owner_id",
    )
    assert "owner_id" not in created
    with SessionLocal() as db:
        row = db.get(LibraryLink, int(created["id"]))
        alice_id = int(db.query(User).filter(User.username == "aiw14_alice").one().id)
    assert row is not None and int(row.owner_id) == alice_id, "owner 必须固定为当前会话用户"


def test_patch_own_link_updates_and_clears_note(ctx: _Ctx) -> None:
    created = _create_link(ctx.client, ctx.alice, "待更新链接", "https://example.com/old")
    updated = _ok(
        ctx.client,
        "PATCH",
        f"/api/library/links/{created['id']}",
        headers=ctx.alice,
        body={"title": "已更新链接", "url": "https://example.com/new", "note": None},
        label="更新本人链接",
    )
    assert updated["title"] == "已更新链接"
    assert updated["url"] == "https://example.com/new"
    assert updated["note"] is None


def test_patch_other_or_missing_link_returns_4040(ctx: _Ctx) -> None:
    created = _create_link(ctx.client, ctx.alice, "他人不可改", "https://example.com/owned")
    _err(
        ctx.client,
        "PATCH",
        f"/api/library/links/{created['id']}",
        headers=ctx.bob,
        body={"title": "越权修改"},
        code=ERR_NOT_FOUND,
        label="他人链接不可改",
    )
    _err(
        ctx.client,
        "PATCH",
        "/api/library/links/99999999",
        headers=ctx.alice,
        body={"title": "不存在"},
        code=ERR_NOT_FOUND,
        label="不存在的链接",
    )
    data = _ok(ctx.client, "GET", "/api/library/links", headers=ctx.alice, label="越权后列表")
    current = {int(item["id"]): item for item in data["items"]}
    assert current[int(created["id"])]["title"] == "他人不可改", "越权 PATCH 不得改写他人数据"


@pytest.mark.parametrize(
    ("title", "url", "note"),
    [
        ("合法标题", "javascript:alert(1)", None),
        ("合法标题", "ftp://example.com/file", None),
        ("合法标题", "https://", None),
        ("", "https://example.com/blank", None),
        ("   ", "https://example.com/blank-title", None),
        ("x" * 201, "https://example.com/long-title", None),
        ("合法标题", "https://example.com/" + "a" * 1001, None),
        ("合法标题", "https://example.com/long-note", "n" * 2001),
    ],
)
def test_invalid_link_fields_return_4001(
    ctx: _Ctx, title: str, url: str, note: str | None
) -> None:
    _err(
        ctx.client,
        "POST",
        "/api/library/links",
        headers=ctx.alice,
        body={"title": title, "url": url, "note": note},
        code=ERR_INVALID_PARAM,
        label=f"非法链接字段 title={title[:8]!r} url={url[:24]!r}",
    )


def test_delete_not_supported_and_data_stays(ctx: _Ctx) -> None:
    created = _create_link(ctx.client, ctx.alice, "不可删除", "https://example.com/keep")
    status, payload = _payload(
        ctx.client, "DELETE", f"/api/library/links/{created['id']}", headers=ctx.alice
    )
    assert status in {404, 405}, f"不提供 DELETE，实际 HTTP {status}（code={payload.get('code')}）"
    data = _ok(ctx.client, "GET", "/api/library/links?limit=50", headers=ctx.alice, label="删除后列表")
    assert int(created["id"]) in {int(item["id"]) for item in data["items"]}


def test_links_persist_across_new_client(ctx: _Ctx) -> None:
    created = _create_link(ctx.client, ctx.alice, "持久化链接", "https://example.com/persist")
    with TestClient(app) as fresh:
        headers = _login(fresh, "aiw14_alice")
        data = _ok(fresh, "GET", "/api/library/links?limit=50", headers=headers, label="重建客户端后列表")
    assert int(created["id"]) in {int(item["id"]) for item in data["items"]}


def test_links_require_login_and_csrf(ctx: _Ctx) -> None:
    _err(
        ctx.client,
        "GET",
        "/api/library/links",
        code=4010,
        status=401,
        label="未登录列表",
    )
    only_cookie = {"Cookie": ctx.alice["Cookie"]}
    _err(
        ctx.client,
        "POST",
        "/api/library/links",
        headers=only_cookie,
        body={"title": "缺 CSRF", "url": "https://example.com/csrf"},
        code=ERR_CSRF,
        status=403,
        label="缺少 CSRF 头",
    )


def test_links_pagination_and_limits(ctx: _Ctx) -> None:
    _ensure_user("aiw14_pager", "Pager")
    pager = _login(ctx.client, "aiw14_pager")
    for index in range(3):
        _create_link(ctx.client, pager, f"分页链接 {index}", f"https://example.com/page/{index}")

    first = _ok(
        ctx.client,
        "GET",
        "/api/library/links?offset=0&limit=2",
        headers=pager,
        label="第一页",
    )
    second = _ok(
        ctx.client,
        "GET",
        "/api/library/links?offset=2&limit=2",
        headers=pager,
        label="第二页",
    )
    assert first["total"] == 3 and len(first["items"]) == 2
    assert second["total"] == 3 and len(second["items"]) == 1
    assert {int(item["id"]) for item in first["items"]}.isdisjoint(
        {int(item["id"]) for item in second["items"]}
    )

    _err(
        ctx.client,
        "GET",
        "/api/library/links?limit=0",
        headers=pager,
        code=ERR_INVALID_PARAM,
        label="limit 下界",
    )
    _err(
        ctx.client,
        "GET",
        "/api/library/links?limit=51",
        headers=pager,
        code=ERR_INVALID_PARAM,
        label="limit 上界",
    )


# --------------------------------------------------------------------------- #
# 「我的活动 / 任务」搜索
# --------------------------------------------------------------------------- #
def _search(ctx: _Ctx, headers: dict[str, str], query: str) -> dict:
    return _ok(
        ctx.client,
        "GET",
        f"/api/search/mine?q={quote(query)}",
        headers=headers,
        label=f"搜索 mine q={query!r}",
    )


def _ids(group: dict) -> set[int]:
    return {int(item["id"]) for item in group["items"]}


def test_search_mine_only_returns_own_objects(ctx: _Ctx) -> None:
    data = _search(ctx, ctx.alice, "alpha")
    assert _ids(data["activities"]) == {ctx.alice_activity}, "活动组只含本人负责 / mine 的活动"
    assert _ids(data["tasks"]) == {ctx.alice_task}, "任务组只含 mine 任务"
    assert data["activities"]["total"] == 1 and data["tasks"]["total"] == 1

    bob_data = _search(ctx, ctx.bob, "alpha")
    assert _ids(bob_data["activities"]) == {ctx.bob_activity}
    assert _ids(bob_data["tasks"]) == {ctx.bob_tasks[0], ctx.bob_tasks[1]}
    assert bob_data["tasks"]["total"] == 2
    assert ctx.alice_task not in _ids(bob_data["tasks"]), "组织内可见但非 mine 的任务不得混入"
    assert ctx.carol_task not in _ids(bob_data["tasks"]), "跨组织 / 匿名对象不得泄漏"


def test_search_mine_excludes_non_mine_visible_activity(ctx: _Ctx) -> None:
    # Alice 是组织管理员，能在大厅看到 Bob 的活动，但搜索只按 mine 范围。
    data = _search(ctx, ctx.alice, "Bob Alpha")
    assert _ids(data["activities"]) == set()
    assert data["activities"]["total"] == 0


def test_search_mine_is_case_insensitive_and_empty_query(ctx: _Ctx) -> None:
    lower = _search(ctx, ctx.bob, "ALPHA")
    assert _ids(lower["tasks"]) == {ctx.bob_tasks[0], ctx.bob_tasks[1]}

    empty = _search(ctx, ctx.bob, "")
    assert empty["activities"] == {"items": [], "total": 0}
    assert empty["tasks"] == {"items": [], "total": 0}

    missing = _ok(ctx.client, "GET", "/api/search/mine", headers=ctx.bob, label="缺省 q")
    assert missing["activities"]["items"] == [] and missing["tasks"]["items"] == []


def test_search_mine_pagination_and_bounds(ctx: _Ctx) -> None:
    limited = _ok(
        ctx.client,
        "GET",
        "/api/search/mine?q=alpha&limit=1",
        headers=ctx.bob,
        label="limit=1",
    )
    assert limited["tasks"]["total"] == 2
    assert len(limited["tasks"]["items"]) == 1

    _err(
        ctx.client,
        "GET",
        "/api/search/mine?q=alpha&limit=0",
        headers=ctx.bob,
        code=ERR_INVALID_PARAM,
        label="搜索 limit 下界",
    )
    _err(
        ctx.client,
        "GET",
        "/api/search/mine?q=alpha&limit=21",
        headers=ctx.bob,
        code=ERR_INVALID_PARAM,
        label="搜索 limit 上界",
    )
    _err(
        ctx.client,
        "GET",
        "/api/search/mine?q=" + "a" * 101,
        headers=ctx.bob,
        code=ERR_INVALID_PARAM,
        label="搜索词超长",
    )


def test_search_mine_task_payload_matches_task_out(ctx: _Ctx) -> None:
    data = _search(ctx, ctx.bob, "物资")
    item = data["tasks"]["items"][0]
    assert item["id"] == ctx.bob_tasks[0]
    assert item["publisher_name"] == "Bob"
    for key in ("status", "claim_type", "publisher_id", "is_claimable", "members", "created_at"):
        assert key in item, f"搜索结果任务项缺少 TaskOut 字段 {key}"


def test_search_mine_does_not_leak_foreign_titles(ctx: _Ctx) -> None:
    data = _search(ctx, ctx.alice, "Alpha")
    titles = {item["title"] for group in ("activities", "tasks") for item in data[group]["items"]}
    assert "Alpha 他人任务" not in titles
    assert "Alpha 外部活动" not in titles


def test_search_mine_requires_login(ctx: _Ctx) -> None:
    _err(
        ctx.client,
        "GET",
        "/api/search/mine?q=alpha",
        code=4010,
        status=401,
        label="未登录搜索",
    )