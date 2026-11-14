#!/usr/bin/env python
"""AIW-14 r4 活动任务表格只读投影测试（契约 `C-ACT-TABLE-DTO@1`）。

覆盖范围：

1. ``build_activity_tree`` 输出 ``start_time``、``assignees``（与 ``assignee_names`` 同序）；
2. 无成员 / 无开始时间时为空列表与 ``None``；
3. 父任务 ``completed_children`` 只计 ``verified``，``cancelled`` 计入分母；
4. 无子任务的任务计数为 ``0/0``；
5. 活动详情 HTTP 接口经 ``_visible_activity_tasks`` 过滤后，不可见任务及其子树不进入树。

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

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw14-activity-table-"))
_TEST_DB_PATH = _TMP_DIR / "aiw14_activity_table.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Activity, OrgMember, Organization, Task, TaskApplication, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import activity_service  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

PASSWORD = "TestPass123!"


@dataclass
class _Ctx:
    client: TestClient
    activity_id: int
    ids: dict[str, int]
    worker_headers: dict[str, str]


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


def _ensure_org(name: str, slug: str, *, admin_id: int, member_ids: tuple[int, ...] = ()) -> int:
    with SessionLocal() as db:
        org = db.query(Organization).filter(Organization.slug == slug).first()
        if org is None:
            org = Organization(name=name, slug=slug, status="active")
            db.add(org)
            db.flush()

        rows = {
            int(row.user_id): row
            for row in db.query(OrgMember).filter(OrgMember.org_id == int(org.id)).all()
        }

        def upsert(user_id: int, role: str) -> None:
            row = rows.get(int(user_id))
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

        upsert(admin_id, "admin")
        for member_id in member_ids:
            upsert(member_id, "member")

        db.commit()
        db.refresh(org)
        return int(org.id)


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    payload = response.json()
    assert response.status_code == 200 and payload.get("code") == 0, (
        f"登录 {username}：期望 HTTP 200 + code=0，实际 HTTP {response.status_code} "
        f"+ code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    values: dict[str, str] = {}
    for raw in response.headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        if name.strip() in {SESSION_COOKIE, CSRF_COOKIE}:
            values[name.strip()] = rest.split(";", 1)[0].strip()
    session = values.get(SESSION_COOKIE)
    csrf = values.get(CSRF_COOKIE)
    assert session and csrf, "登录响应缺少会话 Cookie"
    client.cookies.clear()
    return {
        "Cookie": f"{SESSION_COOKIE}={session}; {CSRF_COOKIE}={csrf}",
        CSRF_HEADER: csrf,
    }


def _add_task(
    db,
    *,
    title: str,
    activity_id: int,
    org_id: int,
    publisher_id: int,
    created_at: str,
    parent_id: int | None = None,
    status: str = "published",
    claim_type: str = "open",
    start_time: str | None = None,
) -> int:
    task = Task(
        title=title,
        activity_id=activity_id,
        org_id=org_id,
        publisher_id=publisher_id,
        parent_id=parent_id,
        status=status,
        claim_type=claim_type,
        start_time=start_time,
        created_at=created_at,
    )
    db.add(task)
    db.flush()
    return int(task.id)


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        owner_id = _ensure_user("r4_owner", "活动负责人", role="publisher")
        worker_id = _ensure_user("r4_worker", "执行同学", role="student")
        helper_id = _ensure_user("r4_helper", "协助同学", role="student")
        org_id = _ensure_org(
            "r4 活动表格测试组织",
            "aiw14-r4-table",
            admin_id=owner_id,
            member_ids=(worker_id, helper_id),
        )
        worker_headers = _login(client, "r4_worker")

        ids: dict[str, int] = {}
        with SessionLocal() as db:
            activity = Activity(
                title="r4-活动表格",
                owner_id=owner_id,
                org_id=org_id,
                created_at="2026-05-01 08:00:00",
            )
            db.add(activity)
            db.flush()
            activity_id = int(activity.id)

            top_a = _add_task(
                db,
                title="r4-有成员有子任务",
                activity_id=activity_id,
                org_id=org_id,
                publisher_id=owner_id,
                created_at="2026-05-01 09:00:00",
                start_time="2026-05-02 09:00",
            )
            sub_verified = _add_task(
                db,
                title="r4-子任务-已验收",
                activity_id=activity_id,
                org_id=org_id,
                publisher_id=owner_id,
                created_at="2026-05-01 09:01:00",
                parent_id=top_a,
                status="verified",
                start_time="2026-05-02 10:00",
            )
            sub_open = _add_task(
                db,
                title="r4-子任务-进行中",
                activity_id=activity_id,
                org_id=org_id,
                publisher_id=owner_id,
                created_at="2026-05-01 09:02:00",
                parent_id=top_a,
            )
            sub_cancelled = _add_task(
                db,
                title="r4-子任务-已取消",
                activity_id=activity_id,
                org_id=org_id,
                publisher_id=owner_id,
                created_at="2026-05-01 09:03:00",
                parent_id=top_a,
                status="cancelled",
            )
            top_b = _add_task(
                db,
                title="r4-无成员无子任务",
                activity_id=activity_id,
                org_id=org_id,
                publisher_id=owner_id,
                created_at="2026-05-01 10:00:00",
            )
            top_hidden = _add_task(
                db,
                title="r4-执行者对成员不可见",
                activity_id=activity_id,
                org_id=org_id,
                publisher_id=owner_id,
                created_at="2026-05-01 11:00:00",
                claim_type="assigned",
            )
            hidden_child = _add_task(
                db,
                title="r4-不可见任务的子任务",
                activity_id=activity_id,
                org_id=org_id,
                publisher_id=owner_id,
                created_at="2026-05-01 11:01:00",
                parent_id=top_hidden,
                claim_type="assigned",
            )

            db.add_all(
                [
                    TaskApplication(task_id=top_a, user_id=worker_id, status="approved"),
                    TaskApplication(task_id=top_a, user_id=helper_id, status="approved"),
                    TaskApplication(task_id=sub_open, user_id=worker_id, status="approved"),
                ]
            )
            db.commit()

            ids = {
                "owner": owner_id,
                "worker": worker_id,
                "helper": helper_id,
                "top_a": top_a,
                "sub_verified": sub_verified,
                "sub_open": sub_open,
                "sub_cancelled": sub_cancelled,
                "top_b": top_b,
                "top_hidden": top_hidden,
                "hidden_child": hidden_child,
            }

        yield _Ctx(
            client=client,
            activity_id=activity_id,
            ids=ids,
            worker_headers=worker_headers,
        )


def _tree(ctx: _Ctx) -> dict[int, dict]:
    with SessionLocal() as db:
        activity = db.get(Activity, ctx.activity_id)
        assert activity is not None, "活动种子数据缺失"
        return {int(node["id"]): node for node in activity_service.build_activity_tree(db, activity)}


def test_assignees_projection_matches_assignee_names(ctx: _Ctx) -> None:
    tree = _tree(ctx)
    node = tree[ctx.ids["top_a"]]

    assert node["assignee_names"] == ["执行同学", "协助同学"], (
        f"assignee_names 应保持原顺序（实际 {node['assignee_names']!r}）"
    )
    assert [item["name"] for item in node["assignees"]] == node["assignee_names"], (
        f"assignees 应与 assignee_names 同序（实际 {node['assignees']!r}）"
    )
    assert {item["user_id"] for item in node["assignees"]} == {ctx.ids["worker"], ctx.ids["helper"]}, (
        f"assignees 应携带 approved 用户 id（实际 {node['assignees']!r}）"
    )
    assert node["start_time"] == "2026-05-02 09:00", f"父任务开始时间应投影（实际 {node['start_time']!r}）"

    child = next(item for item in node["children"] if int(item["id"]) == ctx.ids["sub_open"])
    assert child["start_time"] is None, f"子任务无开始时间应为 None（实际 {child['start_time']!r}）"
    assert child["assignee_names"] == ["执行同学"], f"子任务成员应投影（实际 {child['assignee_names']!r}）"
    assert [item["user_id"] for item in child["assignees"]] == [ctx.ids["worker"]], (
        f"子任务 assignees 应携带用户 id（实际 {child['assignees']!r}）"
    )


def test_empty_members_and_start_time(ctx: _Ctx) -> None:
    tree = _tree(ctx)
    node = tree[ctx.ids["top_b"]]

    assert node["assignees"] == [], f"无成员时 assignees 为空列表（实际 {node['assignees']!r}）"
    assert node["assignee_names"] == [], f"无成员时 assignee_names 为空列表（实际 {node['assignee_names']!r}）"
    assert node["start_time"] is None, f"无开始时间应为 None（实际 {node['start_time']!r}）"
    assert node["completed_children"] == 0 and node["total_children"] == 0, (
        f"无子任务应为 0/0（实际 {node['completed_children']}/{node['total_children']}）"
    )


def test_children_counts_only_verified(ctx: _Ctx) -> None:
    tree = _tree(ctx)
    node = tree[ctx.ids["top_a"]]

    assert node["total_children"] == 3, f"cancelled 应计入分母（实际 {node['total_children']}）"
    assert node["completed_children"] == 1, (
        f"completed_children 只计 verified（实际 {node['completed_children']}）"
    )


def test_nodes_carry_activity_id(ctx: _Ctx) -> None:
    tree = _tree(ctx)
    assert tree, "活动任务树不应为空"

    for node in tree.values():
        assert node["activity_id"] == ctx.activity_id, (
            f"父任务 activity_id 应为 {ctx.activity_id}（实际 {node['activity_id']!r}）"
        )
        for child in node["children"]:
            assert child["activity_id"] == ctx.activity_id, (
                f"子任务 activity_id 应与父任务同值（实际 {child['activity_id']!r}）"
            )


def test_http_detail_excludes_invisible_task_subtree(ctx: _Ctx) -> None:
    response = ctx.client.get(
        f"/api/activities/{ctx.activity_id}", headers=ctx.worker_headers
    )
    payload = response.json()
    assert response.status_code == 200 and payload.get("code") == 0, (
        f"活动详情：期望 HTTP 200 + code=0，实际 HTTP {response.status_code} + code={payload.get('code')} "
        f"（msg={payload.get('msg')}）"
    )
    tasks = payload["data"]["tasks"]
    visible_ids: set[int] = set()
    for node in tasks:
        visible_ids.add(int(node["id"]))
        visible_ids.update(int(child["id"]) for child in (node.get("children") or []))

    assert int(ctx.ids["top_a"]) in visible_ids and int(ctx.ids["top_b"]) in visible_ids, (
        f"可见任务应保留（实际 {sorted(visible_ids)}）"
    )
    assert int(ctx.ids["top_hidden"]) not in visible_ids, "不可见父任务不应进入树"
    assert int(ctx.ids["hidden_child"]) not in visible_ids, "不可见父任务的子任务不应进入树"

    node_a: dict[str, Any] = next(item for item in tasks if int(item["id"]) == ctx.ids["top_a"])
    assert node_a["activity_id"] == ctx.activity_id
    assert [item["user_id"] for item in node_a["assignees"]] == [ctx.ids["worker"], ctx.ids["helper"]]
    assert node_a["completed_children"] == 1 and node_a["total_children"] == 3
    assert node_a["start_time"] == "2026-05-02 09:00"