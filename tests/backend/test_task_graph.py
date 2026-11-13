#!/usr/bin/env python
"""AIW-03 任务依赖图后端行为测试（契约 `C-TASK-GRAPH@1` / `C-ACTIVITY-GRAPH@1`）。

覆盖范围（全部通过真实 HTTP 行为验证）：

1. 多前置创建：边表与 ``depends_on_ids`` 一致，旧 ``depends_on`` 为首项；
2. 多前置全部 ``verified`` 才可报名：未完成返回 4020，全部完成后可正常报名；
3. 非法依赖：跨活动、自依赖、重复、不存在、跨层级均 4001 且不写库；
4. 成环：Patch 制造环返回 4001，原依赖集合不变；
5. 活动图谱：节点与任务树一致，边与任务 ``depends_on_ids`` 一致，时间缺失保持 null；
6. 可见性：无关用户读取活动详情仍 4040，图谱不泄露不可见任务；
7. 任务局部图：前置 / 后继与边只含可见任务。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH``、``MAAS_MOCK=1``、``RUN_SCHEDULER=0``；
不触碰 ``backend/campus.db``。
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

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-task-graph-"))
_TEST_DB_PATH = _TMP_DIR / "task_graph.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import OrgMember, Organization, Task, TaskDependency, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

ERR_INVALID_PARAM = 4001
ERR_DEPENDENCY = 4020
ERR_NOT_FOUND = 4040
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
                db.add(
                    OrgMember(
                        org_id=int(org.id), user_id=int(user_id), role=role, status="active"
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
        owner_id = _ensure_user("graph_owner", "图谱负责人", role="publisher")
        publisher_id = _ensure_user("graph_publisher", "图谱发布者", role="publisher")
        worker_id = _ensure_user("graph_worker", "图谱执行者", role="student")
        outsider_id = _ensure_user("graph_outsider", "图谱路人", role="student")

        org_id = _ensure_org(
            "AIW03 任务图谱组织",
            "aiw03-task-graph",
            roles={owner_id: "collaborator", publisher_id: "admin", worker_id: "member"},
        )
        _ensure_org("AIW03 无关组织", "aiw03-outsider", roles={outsider_id: "member"})

        yield _Ctx(
            client=client,
            owner=_login(client, "graph_owner"),
            publisher=_login(client, "graph_publisher"),
            worker=_login(client, "graph_worker"),
            outsider=_login(client, "graph_outsider"),
            ids={
                "owner": owner_id,
                "publisher": publisher_id,
                "worker": worker_id,
                "outsider": outsider_id,
            },
            org_id=org_id,
        )


def _create_activity(ctx: _Ctx, title: str) -> int:
    return int(
        _ok(
            ctx.client,
            "POST",
            "/api/activities",
            headers=ctx.owner,
            body={"title": title, "org_id": ctx.org_id},
            label=f"创建活动 {title}",
        )["id"]
    )


def _create_task(ctx: _Ctx, title: str, **fields: Any) -> dict:
    return _ok(
        ctx.client,
        "POST",
        "/api/tasks",
        headers=ctx.publisher,
        body={"title": title, **fields},
        label=f"创建任务 {title}",
    )


def _edge_pairs(task_id: int) -> set[tuple[int, int]]:
    with SessionLocal() as db:
        rows = db.query(TaskDependency).filter(TaskDependency.task_id == task_id).all()
        return {(int(row.depends_on_id), int(row.task_id)) for row in rows}


def _finish_task(ctx: _Ctx, task_id: int) -> None:
    """走真实流程把已指派任务推进到 verified。"""
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/progress",
        headers=ctx.worker,
        body={"content": "依赖前置推进"},
        label=f"成员推进任务 #{task_id}",
    )
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/submit", headers=ctx.worker, label="成员提交")
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        headers=ctx.publisher,
        body={"pass": True},
        label=f"验收任务 #{task_id}",
    )


# --------------------------------------------------------------------------- #
# 1. 多前置创建与读取
# --------------------------------------------------------------------------- #
def test_multi_dependency_create_and_read(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "多前置-活动")
    first = _create_task(ctx, "多前置-A", activity_id=activity_id)
    second = _create_task(ctx, "多前置-B", activity_id=activity_id)
    target = _create_task(
        ctx,
        "多前置-C",
        activity_id=activity_id,
        depends_on_ids=[int(first["id"]), int(second["id"])],
    )

    target_id = int(target["id"])
    assert [int(item) for item in target["depends_on_ids"]] == [int(first["id"]), int(second["id"])], (
        f"创建响应应回显两个前置（实际 {target['depends_on_ids']}）"
    )
    assert int(target["depends_on"]) == int(first["id"]), "旧 depends_on 应同步为首个前置"
    assert _edge_pairs(target_id) == {
        (int(first["id"]), target_id),
        (int(second["id"]), target_id),
    }, "边表应写入两条依赖边"

    detail = _ok(ctx.client, "GET", f"/api/tasks/{target_id}", headers=ctx.publisher, label="读取多前置详情")
    assert [int(item) for item in detail["depends_on_ids"]] == [
        int(first["id"]),
        int(second["id"]),
    ], "任务详情应回显全部前置"
    assert {int(item["id"]) for item in detail["dependencies"]} == {
        int(first["id"]),
        int(second["id"]),
    }, "dependencies 应列出全部直接前置"

    listed = _ok(
        ctx.client,
        "GET",
        f"/api/tasks?activity_id={activity_id}",
        headers=ctx.publisher,
        label="按活动列出任务",
    )["items"]
    row = next(item for item in listed if int(item["id"]) == target_id)
    assert len(row["depends_on_ids"]) == 2, f"列表也应返回多前置（实际 {row['depends_on_ids']}）"


# --------------------------------------------------------------------------- #
# 2. 多前置全部完成才可报名
# --------------------------------------------------------------------------- #
def test_all_dependencies_must_be_verified_before_apply(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "解锁-活动")
    first = _create_task(
        ctx,
        "解锁-A",
        activity_id=activity_id,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    second = _create_task(
        ctx,
        "解锁-B",
        activity_id=activity_id,
        claim_type="assign",
        assignee_id=ctx.ids["worker"],
    )
    target = _create_task(
        ctx,
        "解锁-C",
        activity_id=activity_id,
        depends_on_ids=[int(first["id"]), int(second["id"])],
    )
    target_id = int(target["id"])

    blocked = _err(
        ctx.client,
        "POST",
        f"/api/tasks/{target_id}/apply",
        code=ERR_DEPENDENCY,
        headers=ctx.worker,
        label="两个前置都未完成时报名",
    )
    assert "解锁-A" in blocked.get("msg", "") and "解锁-B" in blocked.get("msg", ""), (
        f"4020 消息应列出全部未完成前置（实际 {blocked.get('msg')!r}）"
    )

    _finish_task(ctx, int(first["id"]))
    still_blocked = _err(
        ctx.client,
        "POST",
        f"/api/tasks/{target_id}/apply",
        code=ERR_DEPENDENCY,
        headers=ctx.worker,
        label="仅一个前置完成时报名",
    )
    assert "解锁-A" not in still_blocked.get("msg", ""), "已完成前置不应出现在未完成列表"
    assert "解锁-B" in still_blocked.get("msg", ""), "未完成前置应继续阻塞"

    _finish_task(ctx, int(second["id"]))
    applied = _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{target_id}/apply",
        headers=ctx.worker,
        body={"reason": None},
        label="全部前置完成后报名",
    )
    assert applied["application"]["status"] == "pending", "全部前置完成后应可正常报名"

    detail = _ok(ctx.client, "GET", f"/api/tasks/{target_id}", headers=ctx.worker, label="报名后读详情")
    assert detail["is_claimable"] is False, "已有 pending 报名时 is_claimable 为 false（已报名，非重复可报）"


# --------------------------------------------------------------------------- #
# 3. 非法依赖：跨活动 / 自依赖 / 重复 / 不存在 / 跨层级
# --------------------------------------------------------------------------- #
def test_invalid_dependencies_rejected_without_writes(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        baseline_edges = db.query(TaskDependency).count()

    activity_a = _create_activity(ctx, "非法依赖-活动A")
    activity_b = _create_activity(ctx, "非法依赖-活动B")
    same_activity = _create_task(ctx, "非法依赖-同活动", activity_id=activity_a)
    other_activity = _create_task(ctx, "非法依赖-他活动", activity_id=activity_b)

    cross = _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={
            "title": "非法依赖-跨活动",
            "activity_id": activity_a,
            "depends_on_ids": [int(other_activity["id"])],
        },
        label="跨活动依赖",
    )
    assert "同一活动" in cross.get("msg", ""), f"跨活动应给出明确原因（实际 {cross.get('msg')!r}）"

    duplicate = _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={
            "title": "非法依赖-重复",
            "activity_id": activity_a,
            "depends_on_ids": [int(same_activity["id"]), int(same_activity["id"])],
        },
        label="重复依赖",
    )
    assert "不能重复" in duplicate.get("msg", ""), "重复前置应被拒绝"

    missing = _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={"title": "非法依赖-不存在", "activity_id": activity_a, "depends_on_ids": [999999]},
        label="不存在的前置",
    )
    assert "不存在" in missing.get("msg", ""), "不存在的前置应被拒绝"

    parent = _create_task(ctx, "非法依赖-父任务", activity_id=activity_a)
    parent_id = int(parent["id"])
    child = _create_task(ctx, "非法依赖-子任务", parent_id=parent_id)
    cross_level = _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={
            "title": "非法依赖-跨层级",
            "parent_id": parent_id,
            "depends_on_ids": [int(same_activity["id"])],
        },
        label="跨层级依赖（子任务依赖第一层任务）",
    )
    assert "同一层级" in cross_level.get("msg", ""), "跨层级依赖应被拒绝"

    self_dependency = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{parent_id}",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={"depends_on_ids": [parent_id]},
        label="自依赖",
    )
    assert "依赖自己" in self_dependency.get("msg", ""), "自依赖应被拒绝"

    for task_id in (int(child["id"]), parent_id):
        assert _edge_pairs(task_id) == set(), f"非法依赖不得写边（任务 #{task_id}）"
    rejected_titles = [
        "非法依赖-跨活动",
        "非法依赖-重复",
        "非法依赖-不存在",
        "非法依赖-跨层级",
    ]
    with SessionLocal() as db:
        assert db.query(TaskDependency).count() == baseline_edges, "非法依赖请求不得新增任何边"
        assert (
            db.query(Task).filter(Task.title.in_(rejected_titles)).count() == 0
        ), "校验失败的任务不得落库（4001 应在写库前返回）"


# --------------------------------------------------------------------------- #
# 4. 成环拒绝且原集合不变
# --------------------------------------------------------------------------- #
def test_cycle_is_rejected_and_edges_unchanged(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "成环-活动")
    first = _create_task(ctx, "成环-A", activity_id=activity_id)
    second = _create_task(
        ctx, "成环-B", activity_id=activity_id, depends_on_ids=[int(first["id"])]
    )
    first_id = int(first["id"])

    assert _edge_pairs(first_id) == set(), "A 初始无前置"
    cycle = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{first_id}",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={"depends_on_ids": [int(second["id"])]},
        label="制造 A→B→A 环",
    )
    assert "环" in cycle.get("msg", ""), f"成环应给出明确原因（实际 {cycle.get('msg')!r}）"
    assert _edge_pairs(first_id) == set(), "成环请求失败后 A 的依赖集合不得改变"
    assert _edge_pairs(int(second["id"])) == {(first_id, int(second["id"]))}, "B 的原依赖应保持不变"


# --------------------------------------------------------------------------- #
# 5. 活动图谱与任务列表一致，时间缺失不补值
# --------------------------------------------------------------------------- #
def test_activity_graph_matches_task_list_and_keeps_null_times(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "图谱-活动")
    first = _create_task(
        ctx,
        "图谱-A",
        activity_id=activity_id,
        start_time="2026-11-20 14:00:00",
        deadline="2026-11-20 17:00:00",
    )
    second = _create_task(ctx, "图谱-B", activity_id=activity_id)
    target = _create_task(
        ctx,
        "图谱-C",
        activity_id=activity_id,
        depends_on_ids=[int(first["id"]), int(second["id"])],
    )

    detail = _ok(
        ctx.client,
        "GET",
        f"/api/activities/{activity_id}",
        headers=ctx.publisher,
        label="读取活动图谱",
    )
    graph = detail["graph"]
    tree_ids = {int(node["id"]) for node in detail["tasks"]}
    graph_ids = {int(node["id"]) for node in graph["nodes"]}
    assert graph_ids == tree_ids, f"图谱节点应与任务树一致（图 {graph_ids} / 树 {tree_ids}）"

    nodes = {int(node["id"]): node for node in graph["nodes"]}
    assert nodes[int(first["id"])]["start_time"] == "2026-11-20 14:00:00"
    assert nodes[int(first["id"])]["deadline"] == "2026-11-20 17:00:00"
    assert nodes[int(second["id"])]["start_time"] is None, "缺日期节点不得被补值"
    assert nodes[int(second["id"])]["deadline"] is None, "缺日期节点不得被补值"

    edges = {(int(edge["from_id"]), int(edge["to_id"])) for edge in graph["edges"]}
    assert edges == {
        (int(first["id"]), int(target["id"])),
        (int(second["id"]), int(target["id"])),
    }, f"图谱边应与依赖集合一致（实际 {edges}）"

    listed = _ok(
        ctx.client,
        "GET",
        f"/api/tasks?activity_id={activity_id}",
        headers=ctx.publisher,
        label="图谱对齐任务列表",
    )["items"]
    from_list = {
        (int(dep), int(item["id"])) for item in listed for dep in item["depends_on_ids"]
    }
    assert from_list == edges, f"图与列表必须同源（图 {edges} / 列表 {from_list}）"


# --------------------------------------------------------------------------- #
# 6. 可见性：无关用户看不到活动与图谱
# --------------------------------------------------------------------------- #
def test_graph_does_not_leak_to_outsider(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "图谱-可见性")
    _create_task(ctx, "图谱-可见性任务", activity_id=activity_id)

    _err(
        ctx.client,
        "GET",
        f"/api/activities/{activity_id}",
        code=ERR_NOT_FOUND,
        headers=ctx.outsider,
        label="无关用户读取活动详情",
        status=404,
    )


# --------------------------------------------------------------------------- #
# 7. 任务局部图：前置 / 后继
# --------------------------------------------------------------------------- #
def test_task_local_graph_contains_predecessors_and_successors(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "局部图-活动")
    first = _create_task(ctx, "局部图-A", activity_id=activity_id)
    middle = _create_task(
        ctx, "局部图-B", activity_id=activity_id, depends_on_ids=[int(first["id"])]
    )
    last = _create_task(
        ctx, "局部图-C", activity_id=activity_id, depends_on_ids=[int(middle["id"])]
    )

    detail = _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{int(middle['id'])}",
        headers=ctx.publisher,
        label="读取任务局部图",
    )
    assert {int(item["id"]) for item in detail["dependencies"]} == {int(first["id"])}
    assert {int(item["id"]) for item in detail["dependents"]} == {int(last["id"])}
    local_nodes = {int(node["id"]) for node in detail["graph"]["nodes"]}
    assert local_nodes == {int(first["id"]), int(middle["id"]), int(last["id"])}, (
        f"局部图应含当前及直接前后节点（实际 {local_nodes}）"
    )
    local_edges = {
        (int(edge["from_id"]), int(edge["to_id"])) for edge in detail["graph"]["edges"]
    }
    assert local_edges == {
        (int(first["id"]), int(middle["id"])),
        (int(middle["id"]), int(last["id"])),
    }, f"局部边应完整（实际 {local_edges}）"


def test_children_brief_carries_all_dependency_ids(ctx: _Ctx) -> None:
    """子任务树按 `depends_on_ids` 渲染：父任务详情必须返回子任务的完整前置集合。"""
    activity_id = _create_activity(ctx, "子任务依赖-活动")
    parent = _create_task(ctx, "子任务依赖-父任务", activity_id=activity_id)
    parent_id = int(parent["id"])
    first = _create_task(ctx, "子任务依赖-前置", activity_id=activity_id, parent_id=parent_id)
    third = _create_task(ctx, "子任务依赖-前置二", activity_id=activity_id, parent_id=parent_id)
    second = _create_task(
        ctx,
        "子任务依赖-目标",
        activity_id=activity_id,
        parent_id=parent_id,
        depends_on_ids=[int(first["id"]), int(third["id"])],
    )

    detail = _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{parent_id}",
        headers=ctx.publisher,
        label="读取父任务子任务摘要",
    )
    children = {int(item["id"]): item for item in detail["children"]}
    all_ids = [int(item) for item in children[int(second["id"])]["depends_on_ids"]]
    assert set(all_ids) == {int(first["id"]), int(third["id"])}, "子任务摘要应携带完整前置集合"
    assert all_ids[0] == int(first["id"]), "旧 depends_on 兼容索引应指向集合首项"
    assert int(children[int(second["id"])]["depends_on"]) == int(first["id"])
    assert [int(item) for item in children[int(first["id"])]["depends_on_ids"]] == []


# --------------------------------------------------------------------------- #
# 8. 审查修复回归：跨组织 / PATCH 替换与清空 / 归属变更 / 消息脱敏 / 图过滤
# --------------------------------------------------------------------------- #
def _org_id(slug: str) -> int:
    with SessionLocal() as db:
        org = db.query(Organization).filter(Organization.slug == slug).first()
        assert org is not None, f"测试组织不存在：{slug}"
        return int(org.id)


def _insert_raw_task(activity_id: int, org_id: int, publisher_id: int, title: str) -> int:
    """绕过 API 直接造隔离任务，用于构造“同活动但不可见/跨组织”的审查场景。"""
    with SessionLocal() as db:
        task = Task(
            title=title,
            activity_id=activity_id,
            org_id=org_id,
            publisher_id=publisher_id,
            status="published",
            claim_type="open",
            extras={},
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return int(task.id)


def _insert_raw_edge(task_id: int, depends_on_id: int) -> None:
    with SessionLocal() as db:
        db.add(TaskDependency(task_id=int(task_id), depends_on_id=int(depends_on_id)))
        db.commit()


def test_cross_org_dependency_rejected(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "跨组织-活动")
    foreign_org = _org_id("aiw03-outsider")
    foreign_id = _insert_raw_task(
        activity_id, foreign_org, ctx.ids["outsider"], "跨组织-他组织前置"
    )

    rejected = _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={
            "title": "跨组织-新任务",
            "activity_id": activity_id,
            "depends_on_ids": [foreign_id],
        },
        label="跨组织依赖",
    )
    assert "同一组织" in rejected.get("msg", ""), (
        f"跨组织应给出明确原因（实际 {rejected.get('msg')!r}）"
    )
    with SessionLocal() as db:
        assert (
            db.query(TaskDependency).filter(TaskDependency.depends_on_id == foreign_id).count() == 0
        ), "跨组织依赖不得写边"


def test_activity_graph_drops_invisible_nodes_and_dangling_edges(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "图过滤-活动")
    visible = _create_task(ctx, "图过滤-可见", activity_id=activity_id)
    foreign_org = _org_id("aiw03-outsider")
    hidden_id = _insert_raw_task(
        activity_id, foreign_org, ctx.ids["outsider"], "图过滤-不可见任务"
    )
    _insert_raw_edge(int(visible["id"]), hidden_id)

    detail = _ok(
        ctx.client,
        "GET",
        f"/api/activities/{activity_id}",
        headers=ctx.publisher,
        label="读取部分可见活动图",
    )
    tree_ids = {int(node["id"]) for node in detail["tasks"]}
    graph_ids = {int(node["id"]) for node in detail["graph"]["nodes"]}
    assert hidden_id not in tree_ids, "不可见任务不得出现在任务树"
    assert graph_ids == tree_ids, f"图谱节点应与任务树一致（图 {graph_ids} / 树 {tree_ids}）"
    assert detail["graph"]["edges"] == [], "一端不可见的边必须被丢弃，避免截断连线造成误解"


def test_patch_dependency_replace_clear_and_legacy_field(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "PATCH 依赖-活动")
    first = _create_task(ctx, "PATCH-A", activity_id=activity_id)
    second = _create_task(ctx, "PATCH-B", activity_id=activity_id)
    target = _create_task(
        ctx,
        "PATCH-C",
        activity_id=activity_id,
        depends_on_ids=[int(first["id"]), int(second["id"])],
    )
    target_id = int(target["id"])

    replaced = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{target_id}",
        headers=ctx.publisher,
        body={"depends_on_ids": [int(second["id"])]},
        label="整体替换依赖",
    )
    assert [int(item) for item in replaced["depends_on_ids"]] == [int(second["id"])]
    assert int(replaced["depends_on"]) == int(second["id"])
    assert _edge_pairs(target_id) == {(int(second["id"]), target_id)}

    cleared = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{target_id}",
        headers=ctx.publisher,
        body={"depends_on_ids": []},
        label="空列表清空依赖",
    )
    assert cleared["depends_on_ids"] == [] and cleared["depends_on"] is None
    assert _edge_pairs(target_id) == set()

    legacy = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{target_id}",
        headers=ctx.publisher,
        body={"depends_on": int(first["id"])},
        label="旧单前置字段兼容",
    )
    assert [int(item) for item in legacy["depends_on_ids"]] == [int(first["id"])]
    assert _edge_pairs(target_id) == {(int(first["id"]), target_id)}

    override = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{target_id}",
        headers=ctx.publisher,
        body={"depends_on": int(first["id"]), "depends_on_ids": [int(second["id"])]},
        label="同时传两字段时新字段覆盖",
    )
    assert [int(item) for item in override["depends_on_ids"]] == [int(second["id"])], (
        "显式 depends_on_ids 应覆盖旧 depends_on，而不是合并"
    )
    assert _edge_pairs(target_id) == {(int(second["id"]), target_id)}


def test_placement_change_revalidates_existing_dependencies(ctx: _Ctx) -> None:
    activity_a = _create_activity(ctx, "归属变更-活动A")
    activity_b = _create_activity(ctx, "归属变更-活动B")
    dependency = _create_task(ctx, "归属变更-前置", activity_id=activity_a)
    target = _create_task(
        ctx,
        "归属变更-任务",
        activity_id=activity_a,
        depends_on_ids=[int(dependency["id"])],
    )
    target_id = int(target["id"])

    rejected = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{target_id}",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={"activity_id": activity_b},
        label="带依赖跨活动移动",
    )
    assert "同一活动" in rejected.get("msg", ""), (
        f"归属变更应重新校验旧依赖（实际 {rejected.get('msg')!r}）"
    )
    detail = _ok(
        ctx.client, "GET", f"/api/tasks/{target_id}", headers=ctx.publisher, label="失败后读任务"
    )
    assert int(detail["activity_id"]) == activity_a, "校验失败时活动归属不得改变"
    assert _edge_pairs(target_id) == {(int(dependency["id"]), target_id)}, "校验失败时依赖不得改变"

    # `depends_on_ids=null` 表示“不修改依赖”，不能被当作已显式处理而跳过归属重校验
    bypass = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{target_id}",
        code=ERR_INVALID_PARAM,
        headers=ctx.publisher,
        body={"activity_id": activity_b, "depends_on_ids": None},
        label="depends_on_ids=null 时跨活动移动",
    )
    assert "同一活动" in bypass.get("msg", ""), (
        f"null 依赖不得绕过归属重校验（实际 {bypass.get('msg')!r}）"
    )
    after = _ok(
        ctx.client, "GET", f"/api/tasks/{target_id}", headers=ctx.publisher, label="绕过失败后读任务"
    )
    assert int(after["activity_id"]) == activity_a, "null 绕过失败时活动归属不得改变"
    assert _edge_pairs(target_id) == {(int(dependency["id"]), target_id)}, "null 绕过失败时依赖不得改变"

    # 合法路径：显式替换为活动 B 内的前置后，跨活动移动成功且依赖集合同步
    new_dependency = _create_task(ctx, "归属变更-新前置", activity_id=activity_b)
    moved = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{target_id}",
        headers=ctx.publisher,
        body={
            "activity_id": activity_b,
            "depends_on_ids": [int(new_dependency["id"])],
        },
        label="显式替换依赖后跨活动移动",
    )
    assert int(moved["activity_id"]) == activity_b, "合法移动应落库"
    assert [int(item) for item in moved["depends_on_ids"]] == [int(new_dependency["id"])]
    assert _edge_pairs(target_id) == {(int(new_dependency["id"]), target_id)}


def test_apply_message_hides_invisible_dependency_titles(ctx: _Ctx) -> None:
    activity_id = _create_activity(ctx, "消息脱敏-活动")
    foreign_org = _org_id("aiw03-outsider")
    hidden_title = "秘密前置标题-不应出现在错误消息"
    hidden_id = _insert_raw_task(activity_id, foreign_org, ctx.ids["outsider"], hidden_title)
    target = _create_task(ctx, "消息脱敏-目标任务", activity_id=activity_id)
    _insert_raw_edge(int(target["id"]), hidden_id)

    blocked = _err(
        ctx.client,
        "POST",
        f"/api/tasks/{int(target['id'])}/apply",
        code=ERR_DEPENDENCY,
        headers=ctx.worker,
        label="前置不可见时报名",
    )
    message = str(blocked.get("msg", ""))
    assert hidden_title not in message, f"4020 消息不得泄露不可见前置标题（实际 {message!r}）"
    assert "不可见" in message, f"消息应说明存在不可见前置（实际 {message!r}）"
