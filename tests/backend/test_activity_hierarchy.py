#!/usr/bin/env python
"""阶段 1 活动层级与进度后端行为测试（契约 `C-DATA-ACTIVITY@1` / `C-HIERARCHY@1` /
`C-ACTIVITY-API@1` / `C-TASK-FIELDS@1` / `C-MIGRATION-2@1`）。

覆盖范围（全部通过真实 HTTP 行为验证，不做字符串/源码检查）：

1. 三层结构：任务不能以自己为父；子任务不可继续拆分；非法请求不写库；
2. 活动归属：子任务继承父任务 ``activity_id``；跨活动挂父任务被 4001 拒绝；
   不存在的活动被 4001 拒绝；
3. 子项完成 ≠ 上层验收：子任务全部 ``verified`` 后父任务仍 ``published``，
   活动进度 ``completed_tasks`` / ``percent`` 不变，仅 ``awaiting_owner_confirm`` 置真；
4. 进度口径：``cancelled`` 顶层任务不计入 ``total_tasks``（不进分母）但计入
   ``cancelled_tasks``；空活动进度为零；
5. 活动列表（``created_at DESC, id DESC`` + ``owner_name`` + ``progress``）、
   详情任务树（一层按创建顺序、子任务挂载顺序、``assignee_names``）、
   活动不存在 4040、未登录 401/4010、创建活动去空白与默认值；
6. ``GET /api/tasks?activity_id=`` 过滤及与 ``include_sub`` / ``status`` 的组合，
   ``TaskOut.activity_id`` / ``activity_title`` / ``parent_title`` 回显；
7. 迁移幂等：旧库补 ``tasks.activity_id`` 列与 ``ix_tasks_activity_id`` 索引，
   重复执行不重复加列、不报错、旧行保持 ``NULL``；空库调用不报错；
   当前库重复 ``init_db()`` 不改变行数。

隔离性：在导入 ``app`` 之前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立
SQLite 文件，关闭调度器并强制 ``MAAS_MOCK=1``；不触碰 ``backend/campus.db``。

认证（阶段 2 `C-SESSION@1`）：fixture 直接写库准备 ``teacher01`` / ``student01``
（``password_hash=hash_password("TestPass123!")``、``status='active'``）以及一个组织
（teacher 为 ``admin``、student 为 ``member``，保证开放任务对学生可见、可报名），
再 ``POST /api/auth/login``（账号 + 密码）。从响应 ``Set-Cookie`` 提取
``cta_session`` / ``cta_csrf``，组装显式 ``Cookie`` 与 ``X-CSRF-Token`` 请求头；
不依赖共享 client 的 cookie jar，以便同一测试同时持有多身份。

可独立运行：``pytest tests/backend/test_activity_hierarchy.py``。
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-activity-hierarchy-"))
_TEST_DB_PATH = _TMP_DIR / "activity_hierarchy.db"

# 必须在导入 app 之前完成：app.db 在模块导入时按 DATABASE_PATH 创建引擎。
os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app.db import SessionLocal, _column_names, _migrate, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import OrgMember, Organization, Task, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040
ERR_UNAUTHORIZED = 4010

#: 测试账号的固定密码；fixture 直接写 ``password_hash`` 与 ``status='active'``。
PASSWORD = "TestPass123!"

DEFAULT_PROGRESS = {
    "total_tasks": 0,
    "completed_tasks": 0,
    "cancelled_tasks": 0,
    "subtask_total": 0,
    "subtask_completed": 0,
    "percent": 0,
    "awaiting_owner_confirm": False,
}


@dataclass
class _Ctx:
    client: TestClient
    teacher: dict[str, str]
    student: dict[str, str]
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


def _ensure_org(name: str, slug: str, *, admin_id: int, member_ids: tuple[int, ...] = ()) -> int:
    """直接写库准备组织与成员关系，保证学生对自己可见的开放任务可报名。"""
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

        def upsert(user_id: int, role: str) -> None:
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

        upsert(admin_id, "admin")
        for member_id in member_ids:
            upsert(member_id, "member")

        db.commit()
        db.refresh(org)
        return int(org.id)


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        teacher_id = _ensure_user("teacher01", "王老师", role="publisher")
        student_id = _ensure_user("student01", "李同学", role="student")
        org_id = _ensure_org(
            "阶段 1 层级测试组织",
            "phase1-hierarchy",
            admin_id=teacher_id,
            member_ids=(student_id,),
        )

        teacher_headers, teacher_user = _login(client, "teacher01")
        student_headers, student_user = _login(client, "student01")
        assert int(teacher_user["id"]) == teacher_id, "teacher01 登录用户应为种子用户"
        assert int(student_user["id"]) == student_id, "student01 登录用户应为种子用户"

        yield _Ctx(
            client=client,
            teacher=teacher_headers,
            student=student_headers,
            ids={"teacher01": teacher_id, "student01": student_id},
            org_id=org_id,
        )


# --------------------------------------------------------------------------- #
# 业务辅助
# --------------------------------------------------------------------------- #
def _create_activity(ctx: _Ctx, title: str, **fields: Any) -> dict:
    return _ok(
        ctx.client,
        "POST",
        "/api/activities",
        headers=ctx.teacher,
        body={"title": title, "org_id": ctx.org_id, **fields},
        label=f"创建活动「{title}」",
    )


def _create_task(ctx: _Ctx, title: str, **fields: Any) -> dict:
    return _ok(
        ctx.client,
        "POST",
        "/api/tasks",
        headers=ctx.teacher,
        body={"title": title, "org_id": ctx.org_id, **fields},
        label=f"发布任务「{title}」",
    )


def _activity_detail(ctx: _Ctx, activity_id: int) -> dict:
    return _ok(ctx.client, "GET", f"/api/activities/{activity_id}", headers=ctx.teacher, label=f"活动 {activity_id} 详情")


def _activity_progress(ctx: _Ctx, activity_id: int) -> dict:
    progress = _activity_detail(ctx, activity_id).get("progress")
    assert isinstance(progress, dict), f"活动 {activity_id} 缺少 progress 对象"
    return progress


def _activity_tasks(ctx: _Ctx, activity_id: int, *, include_sub: bool = True) -> list[dict]:
    suffix = "&include_sub=true" if include_sub else ""
    data = _ok(
        ctx.client,
        "GET",
        f"/api/tasks?activity_id={activity_id}{suffix}",
        headers=ctx.teacher,
        label=f"活动 {activity_id} 任务列表",
    )
    items = data.get("items")
    assert isinstance(items, list), f"活动 {activity_id} 任务列表 items 不是数组"
    return items


def _get_task(ctx: _Ctx, task_id: int) -> dict:
    return _ok(ctx.client, "GET", f"/api/tasks/{task_id}", headers=ctx.teacher, label=f"任务 {task_id} 详情")


def _apply_and_approve(ctx: _Ctx, task_id: int) -> int:
    applied = _ok(
        ctx.client, "POST", f"/api/tasks/{task_id}/apply", headers=ctx.student, label=f"报名任务 {task_id}"
    )
    application_id = int(applied["application"]["id"])
    _ok(
        ctx.client,
        "POST",
        f"/api/applications/{application_id}/decide",
        headers=ctx.teacher,
        body={"approve": True},
        label=f"审批通过任务 {task_id}",
    )
    return application_id


def _complete_task(ctx: _Ctx, task_id: int) -> dict:
    """让学生完成并让老师验收该任务，返回 verify 响应 data。"""
    _apply_and_approve(ctx, task_id)
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/progress",
        headers=ctx.student,
        body={"content": f"任务 {task_id} 执行中"},
        label=f"任务 {task_id} 进度",
    )
    _ok(ctx.client, "POST", f"/api/tasks/{task_id}/submit", headers=ctx.student, label=f"任务 {task_id} 提交")
    return _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        headers=ctx.teacher,
        body={"pass": True},
        label=f"任务 {task_id} 验收",
    )


def _cancel_task(ctx: _Ctx, task_id: int) -> dict:
    return _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.teacher,
        body={"status": "cancelled"},
        label=f"取消任务 {task_id}",
    )


# --------------------------------------------------------------------------- #
# 1. 三层结构与父子循环
# --------------------------------------------------------------------------- #
def test_hierarchy_rejects_self_parent_and_third_level(ctx: _Ctx) -> None:
    activity = _create_activity(ctx, "层级-三层结构")
    activity_id = int(activity["id"])
    top = _create_task(ctx, "层级-顶层任务", activity_id=activity_id)
    top_id = int(top["id"])
    sub = _create_task(ctx, "层级-子任务", parent_id=top_id)
    sub_id = int(sub["id"])

    assert int(top["activity_id"]) == activity_id, f"顶层任务落库 activity_id 应为 {activity_id}（实际 {top['activity_id']}）"
    assert int(sub["activity_id"]) == activity_id, f"子任务应继承父任务 activity_id（实际 {sub['activity_id']}）"
    assert int(sub["parent_id"]) == top_id, f"子任务 parent_id 应为 {top_id}（实际 {sub['parent_id']}）"

    sub_detail = _get_task(ctx, sub_id)
    assert sub_detail.get("parent_title") == "层级-顶层任务", f"子任务详情 parent_title 回显父标题（实际 {sub_detail.get('parent_title')!r}）"
    assert sub_detail.get("activity_title") == "层级-三层结构", f"子任务详情 activity_title 回显活动标题（实际 {sub_detail.get('activity_title')!r}）"

    third = _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={"title": "层级-第三层", "parent_id": sub_id},
        label="子任务的子任务应被拒绝",
    )
    assert third.get("msg") == "子任务不可继续拆分", f"三层限制文案应逐字返回（实际 {third.get('msg')!r}）"

    self_parent = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{top_id}",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={"parent_id": top_id},
        label="任务以自己为父任务应被拒绝",
    )
    assert self_parent.get("msg") == "任务不能以自己为父任务", f"父子循环文案应逐字返回（实际 {self_parent.get('msg')!r}）"

    remaining = _activity_tasks(ctx, activity_id)
    assert {int(item["id"]) for item in remaining} == {top_id, sub_id}, (
        f"非法层级请求不得写入新任务（实际 {[int(item['id']) for item in remaining]}）"
    )
    assert _get_task(ctx, top_id).get("parent_id") is None, "自我为父的 PATCH 失败后顶层任务 parent_id 必须保持 null"


# --------------------------------------------------------------------------- #
# 2. 跨活动错误关联
# --------------------------------------------------------------------------- #
def test_cross_activity_parent_child_and_missing_activity(ctx: _Ctx) -> None:
    activity_a = _create_activity(ctx, "跨活动-甲")
    activity_b = _create_activity(ctx, "跨活动-乙")
    activity_a_id = int(activity_a["id"])
    activity_b_id = int(activity_b["id"])

    top_a = _create_task(ctx, "跨活动-甲顶层", activity_id=activity_a_id)
    top_a_id = int(top_a["id"])

    mismatch = _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={"title": "跨活动-错误子任务", "parent_id": top_a_id, "activity_id": activity_b_id},
        label="子任务与父任务活动不一致应被拒绝",
    )
    assert mismatch.get("msg") == "子任务必须与父任务属于同一活动", (
        f"跨活动关联文案应逐字返回（实际 {mismatch.get('msg')!r}）"
    )

    orphan = _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={"title": "跨活动-孤儿任务", "activity_id": 999999},
        label="不存在的活动应被拒绝",
    )
    assert orphan.get("msg") == "活动不存在", f"活动不存在文案应逐字返回（实际 {orphan.get('msg')!r}）"

    moved = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{top_a_id}",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={"activity_id": 999999},
        label="修改任务到不存在的活动应被拒绝",
    )
    assert moved.get("msg") == "活动不存在", f"PATCH 活动不存在文案应逐字返回（实际 {moved.get('msg')!r}）"

    assert [int(item["id"]) for item in _activity_tasks(ctx, activity_a_id, include_sub=False)] == [top_a_id], (
        "失败请求不得写入新任务"
    )
    assert _activity_tasks(ctx, activity_b_id, include_sub=False) == [], "乙活动不应被错误挂入任务"
    assert int(_get_task(ctx, top_a_id)["activity_id"]) == activity_a_id, "失败 PATCH 不得改写原 activity_id"

    inherited = _create_task(ctx, "跨活动-继承活动", parent_id=top_a_id)
    assert int(inherited["activity_id"]) == activity_a_id, "未显式给 activity_id 的子任务应继承父任务活动"


# --------------------------------------------------------------------------- #
# 3. 子项完成与上层验收的区别
# --------------------------------------------------------------------------- #
def test_subtask_completion_does_not_verify_parent_or_activity(ctx: _Ctx) -> None:
    activity = _create_activity(ctx, "进度-子项不等于验收")
    activity_id = int(activity["id"])
    top = _create_task(ctx, "进度-父任务", activity_id=activity_id)
    top_id = int(top["id"])
    sub = _create_task(ctx, "进度-子任务", parent_id=top_id)
    sub_id = int(sub["id"])

    initial = _activity_progress(ctx, activity_id)
    assert initial["total_tasks"] == 1, f"仅顶层任务计入分母（实际 {initial['total_tasks']}）"
    assert initial["completed_tasks"] == 0, f"初始完成数为 0（实际 {initial['completed_tasks']}）"
    assert initial["subtask_total"] == 1, f"子任务总数应为 1（实际 {initial['subtask_total']}）"
    assert initial["awaiting_owner_confirm"] is False, "子任务未完成时不得标记待负责人确认"
    assert initial["percent"] == 0, f"初始进度为 0（实际 {initial['percent']}）"

    _complete_task(ctx, sub_id)

    after_subtask = _activity_progress(ctx, activity_id)
    assert after_subtask["subtask_completed"] == 1, f"子任务完成数应为 1（实际 {after_subtask['subtask_completed']}）"
    assert after_subtask["completed_tasks"] == 0, "子任务完成不得计入顶层已完成数"
    assert after_subtask["percent"] == 0, f"子任务完成不得改变活动进度（实际 {after_subtask['percent']}）"
    assert after_subtask["awaiting_owner_confirm"] is True, "子任务全部验收后仅标记待负责人确认"

    assert _get_task(ctx, sub_id)["status"] == "verified", "子任务状态应为 verified"
    assert _get_task(ctx, top_id)["status"] != "verified", "子任务完成不得使父任务变 verified"
    tree = _activity_detail(ctx, activity_id)["tasks"]
    top_node = next(node for node in tree if int(node["id"]) == top_id)
    assert top_node["status"] != "verified", f"活动树中父任务仍非 verified（实际 {top_node['status']}）"
    assert [int(child["id"]) for child in top_node["children"]] == [sub_id], "活动树应挂载该子任务"
    assert top_node["children"][0]["status"] == "verified", "活动树子任务状态应同步为 verified"
    assert _activity_detail(ctx, activity_id)["status"] == "published", "子任务完成不得改写活动状态"

    _complete_task(ctx, top_id)

    final = _activity_progress(ctx, activity_id)
    assert final["completed_tasks"] == 1, f"父任务验收后完成数为 1（实际 {final['completed_tasks']}）"
    assert final["percent"] == 100, f"父任务验收后进度 100（实际 {final['percent']}）"
    assert final["awaiting_owner_confirm"] is False, "父任务已验收后不再等待负责人确认"
    assert final["subtask_completed"] == 1, "子任务完成数保持 1"
    assert _activity_detail(ctx, activity_id)["status"] == "published", "任务验收不改写活动 status（本轮只写 published）"


# --------------------------------------------------------------------------- #
# 4. 取消事项在分母中的处理
# --------------------------------------------------------------------------- #
def test_progress_excludes_cancelled_tasks_from_denominator(ctx: _Ctx) -> None:
    activity = _create_activity(ctx, "进度-取消不进分母")
    activity_id = int(activity["id"])
    done = _create_task(ctx, "进度-已完成", activity_id=activity_id)
    cancelled = _create_task(ctx, "进度-已取消", activity_id=activity_id)
    pending = _create_task(ctx, "进度-进行中", activity_id=activity_id)

    _complete_task(ctx, int(done["id"]))
    _cancel_task(ctx, int(cancelled["id"]))

    progress = _activity_progress(ctx, activity_id)
    assert progress["total_tasks"] == 2, f"取消任务不计入 total_tasks（实际 {progress['total_tasks']}）"
    assert progress["completed_tasks"] == 1, f"已完成数为 1（实际 {progress['completed_tasks']}）"
    assert progress["cancelled_tasks"] == 1, f"取消数为 1（实际 {progress['cancelled_tasks']}）"
    assert progress["percent"] == 50, (
        f"1/2 应为 50%；若取消事项留在分母会得到 33%（实际 {progress['percent']}）"
    )

    sub = _create_task(ctx, "进度-将被取消的子任务", parent_id=int(pending["id"]))
    _cancel_task(ctx, int(sub["id"]))

    _cancel_task(ctx, int(pending["id"]))
    progress_all_cancelled = _activity_progress(ctx, activity_id)
    assert progress_all_cancelled["total_tasks"] == 1, f"只剩 1 个未取消顶层任务（实际 {progress_all_cancelled['total_tasks']}）"
    assert progress_all_cancelled["completed_tasks"] == 1, "已完成数保持 1"
    assert progress_all_cancelled["cancelled_tasks"] == 2, f"取消数为 2（实际 {progress_all_cancelled['cancelled_tasks']}）"
    assert progress_all_cancelled["percent"] == 100, f"1/1 应为 100%（实际 {progress_all_cancelled['percent']}）"
    assert progress_all_cancelled["subtask_total"] == 1, "取消的子任务仍计入 subtask_total（契约按全部子任务计数）"
    assert progress_all_cancelled["subtask_completed"] == 0, "取消的子任务不计入 subtask_completed"

    empty = _create_activity(ctx, "进度-空活动")
    empty_progress = _activity_progress(ctx, int(empty["id"]))
    assert {key: empty_progress[key] for key in DEFAULT_PROGRESS} == DEFAULT_PROGRESS, (
        f"空活动进度应全为零值（实际 {empty_progress}）"
    )


# --------------------------------------------------------------------------- #
# 5. 活动列表 / 详情 / 创建
# --------------------------------------------------------------------------- #
def test_activity_list_order_and_owner_progress(ctx: _Ctx) -> None:
    created_ids = [int(_create_activity(ctx, f"列表-活动{index}")["id"]) for index in (1, 2, 3)]

    data = _ok(ctx.client, "GET", "/api/activities", headers=ctx.teacher, label="活动列表")
    items = data.get("items")
    assert isinstance(items, list), "活动列表 items 不是数组"

    positions = [index for index, item in enumerate(items) if int(item["id"]) in created_ids]
    assert len(positions) == 3, f"新建的 3 个活动都应出现在列表中（实际 {len(positions)}）"
    ordered = [int(items[index]["id"]) for index in positions]
    assert ordered == list(reversed(created_ids)), (
        f"活动列表按 created_at DESC, id DESC 排序（期望 {list(reversed(created_ids))}，实际 {ordered}）"
    )

    for index in positions:
        item = items[index]
        assert int(item["owner_id"]) == ctx.ids["teacher01"], f"owner_id 应为当前创建者（实际 {item['owner_id']}）"
        assert item["owner_name"] == "王老师", f"owner_name 应回显展示名（实际 {item['owner_name']!r}）"
        assert item["status"] == "published", f"新活动状态固定 published（实际 {item['status']!r}）"
        assert {key: item["progress"][key] for key in DEFAULT_PROGRESS} == DEFAULT_PROGRESS, (
            f"列表项 progress 应包含完整零值字段（实际 {item['progress']}）"
        )


def test_activity_detail_tree_and_errors(ctx: _Ctx) -> None:
    activity = _create_activity(ctx, "详情-任务树")
    activity_id = int(activity["id"])
    top_1 = _create_task(ctx, "详情-顶层一", activity_id=activity_id)
    top_1_id = int(top_1["id"])
    sub_1 = _create_task(ctx, "详情-子一", parent_id=top_1_id)
    _apply_and_approve(ctx, top_1_id)
    top_2 = _create_task(ctx, "详情-顶层二", activity_id=activity_id)
    top_2_id = int(top_2["id"])
    sub_2a = _create_task(ctx, "详情-子二A", parent_id=top_2_id)
    sub_2b = _create_task(ctx, "详情-子二B", parent_id=top_2_id)

    detail = _activity_detail(ctx, activity_id)
    assert [int(node["id"]) for node in detail["tasks"]] == [top_1_id, top_2_id], (
        f"一层任务按 created_at ASC, id ASC（实际 {[int(node['id']) for node in detail['tasks']]}）"
    )
    children_1 = detail["tasks"][0]["children"]
    children_2 = detail["tasks"][1]["children"]
    assert [int(node["id"]) for node in children_1] == [int(sub_1["id"])], "子任务应挂在正确父节点下"
    assert [int(node["id"]) for node in children_2] == [int(sub_2a["id"]), int(sub_2b["id"])], (
        "同一父任务下子任务按创建顺序挂载"
    )
    assert detail["tasks"][0]["assignee_names"] == ["李同学"], (
        f"已审批成员应出现在 assignee_names（实际 {detail['tasks'][0]['assignee_names']}）"
    )
    assert detail["tasks"][1]["assignee_names"] == [], "无成员任务的 assignee_names 应为空数组"
    assert all("children" not in node for node in children_2), "子任务节点不得再嵌套 children（仅三层）"

    missing = _err(
        ctx.client,
        "GET",
        "/api/activities/999999",
        code=ERR_NOT_FOUND,
        headers=ctx.teacher,
        label="不存在的活动详情",
        status=404,
    )
    assert missing.get("msg") == "活动不存在", f"活动不存在文案应逐字返回（实际 {missing.get('msg')!r}）"

    unauthorized = _err(
        ctx.client,
        "GET",
        "/api/activities",
        code=ERR_UNAUTHORIZED,
        label="未登录读取活动列表",
        status=401,
    )
    assert unauthorized.get("msg") == "未登录或登录已过期", (
        f"未登录文案应逐字返回（实际 {unauthorized.get('msg')!r}）"
    )


def test_create_activity_trims_title_and_rejects_blank(ctx: _Ctx) -> None:
    created = _create_activity(ctx, "  阶段 1 活动甲  ", description="描述", location="教三楼", org="计算机学院")
    assert created.get("title") == "阶段 1 活动甲", f"标题应去除首尾空白（实际 {created.get('title')!r}）"
    assert created.get("description") == "描述", "描述应原样保存"
    assert created.get("location") == "教三楼", "地点应原样保存"
    assert created.get("org") == "计算机学院", "组织应原样保存"
    assert int(created["owner_id"]) == ctx.ids["teacher01"], "owner_id 取当前登录用户"
    assert created.get("owner_name") == "王老师", f"owner_name 应回显展示名（实际 {created.get('owner_name')!r}）"
    assert created.get("status") == "published", "新活动 status 固定 published"
    assert {key: created["progress"][key] for key in DEFAULT_PROGRESS} == DEFAULT_PROGRESS, (
        f"新活动进度应全为零值（实际 {created['progress']}）"
    )

    blank = _err(
        ctx.client,
        "POST",
        "/api/activities",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={"title": "   "},
        label="空白标题活动",
    )
    assert blank.get("msg") == "活动标题不能为空", f"空白标题文案应逐字返回（实际 {blank.get('msg')!r}）"

    auto_created = _create_activity(ctx, "去空白标题-自动创建")
    assert auto_created.get("title") == "去空白标题-自动创建", "正常标题不应被改写"

    invalid = _err(
        ctx.client,
        "POST",
        "/api/activities",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={},
        label="缺少 title 的活动",
    )
    assert invalid.get("msg") == "参数校验失败", f"Pydantic 校验失败统一 4001（实际 {invalid.get('msg')!r}）"


# --------------------------------------------------------------------------- #
# 6. GET /api/tasks 的 activity_id 过滤
# --------------------------------------------------------------------------- #
def test_list_tasks_filters_by_activity(ctx: _Ctx) -> None:
    activity_a = _create_activity(ctx, "过滤-活动甲")
    activity_b = _create_activity(ctx, "过滤-活动乙")
    activity_a_id = int(activity_a["id"])
    activity_b_id = int(activity_b["id"])

    top_a = _create_task(ctx, "过滤-甲顶层", activity_id=activity_a_id)
    top_a_id = int(top_a["id"])
    sub_a = _create_task(ctx, "过滤-甲子任务", parent_id=top_a_id)
    sub_a_id = int(sub_a["id"])
    top_b = _create_task(ctx, "过滤-乙顶层", activity_id=activity_b_id)
    top_b_id = int(top_b["id"])

    only_a = _activity_tasks(ctx, activity_a_id, include_sub=False)
    assert [int(item["id"]) for item in only_a] == [top_a_id], "默认 include_sub=false 时只返回顶层任务"
    assert int(only_a[0]["activity_id"]) == activity_a_id, "TaskOut.activity_id 应回显所属活动"

    with_subs = _activity_tasks(ctx, activity_a_id, include_sub=True)
    assert {int(item["id"]) for item in with_subs} == {top_a_id, sub_a_id}, (
        f"include_sub=true 时包含顶层与子任务（实际 {[int(item['id']) for item in with_subs]}）"
    )
    sub_item = next(item for item in with_subs if int(item["id"]) == sub_a_id)
    assert int(sub_item["activity_id"]) == activity_a_id, "子任务列表项 activity_id 应继承活动"
    assert int(sub_item["parent_id"]) == top_a_id, "子任务列表项 parent_id 应保持"

    only_b = _activity_tasks(ctx, activity_b_id, include_sub=False)
    assert [int(item["id"]) for item in only_b] == [top_b_id], (
        f"activity_id={activity_b_id} 只返回乙活动任务（实际 {[int(item['id']) for item in only_b]}）"
    )

    all_tasks = _ok(ctx.client, "GET", "/api/tasks", headers=ctx.teacher, label="无活动过滤的任务列表")["items"]
    all_ids = {int(item["id"]) for item in all_tasks}
    assert {top_a_id, top_b_id}.issubset(all_ids), "不传 activity_id 时行为应保持不变（不缩小结果集）"
    assert sub_a_id not in all_ids, "不传 activity_id 且默认 include_sub=false 时不返回子任务"

    combined = _ok(
        ctx.client,
        "GET",
        f"/api/tasks?activity_id={activity_a_id}&status=published&include_sub=true",
        headers=ctx.teacher,
        label="活动 + 状态组合过滤",
    )["items"]
    assert {int(item["id"]) for item in combined} == {top_a_id, sub_a_id}, (
        f"activity_id 可与 status/include_sub 组合（实际 {[int(item['id']) for item in combined]}）"
    )

    top_a_detail = _get_task(ctx, top_a_id)
    assert top_a_detail.get("activity_title") == "过滤-活动甲", (
        f"顶层任务详情 activity_title 应为活动标题（实际 {top_a_detail.get('activity_title')!r}）"
    )
    assert top_a_detail.get("parent_title") is None, "顶层任务 parent_title 应为 null"
    sub_a_detail = _get_task(ctx, sub_a_id)
    assert sub_a_detail.get("parent_title") == "过滤-甲顶层", (
        f"子任务详情 parent_title 应为父任务标题（实际 {sub_a_detail.get('parent_title')!r}）"
    )
    assert sub_a_detail.get("activity_title") == "过滤-活动甲", "子任务详情 activity_title 应为活动标题"


# --------------------------------------------------------------------------- #
# 7. PATCH 的活动归属语义与异常数据防御
# --------------------------------------------------------------------------- #
def test_patch_task_activity_placement_semantics(ctx: _Ctx) -> None:
    activity = _create_activity(ctx, "PATCH-活动归属")
    activity_id = int(activity["id"])
    top = _create_task(ctx, "PATCH-顶层", activity_id=activity_id)
    top_id = int(top["id"])

    renamed = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{top_id}",
        headers=ctx.teacher,
        body={"title": "PATCH-顶层改名"},
        label="只改标题",
    )
    assert renamed.get("title") == "PATCH-顶层改名", "标题应更新"
    assert int(renamed["activity_id"]) == activity_id, "只改标题不得清空 activity_id"
    assert renamed.get("parent_id") is None, "只改标题不得改变 parent_id"

    standalone = _create_task(ctx, "PATCH-独立任务")
    assert standalone.get("activity_id") is None, "前置条件：独立任务无活动"
    attached = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{int(standalone['id'])}",
        headers=ctx.teacher,
        body={"activity_id": activity_id},
        label="独立任务挂到活动",
    )
    assert int(attached["activity_id"]) == activity_id, "PATCH activity_id 应落库"
    assert attached.get("parent_id") is None, "挂活动不得改变 parent 层级"

    other = _create_task(ctx, "PATCH-独立任务二")
    other_id = int(other["id"])
    attached_child = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{other_id}",
        headers=ctx.teacher,
        body={"parent_id": top_id},
        label="独立任务挂到父任务",
    )
    assert int(attached_child["parent_id"]) == top_id, "PATCH parent_id 应落库"
    assert int(attached_child["activity_id"]) == activity_id, "挂到父任务后应继承父任务活动"

    detached = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{other_id}",
        headers=ctx.teacher,
        body={"parent_id": None},
        label="子任务解除父级",
    )
    assert detached.get("parent_id") is None, "显式 null 应清空 parent_id"
    assert int(detached["activity_id"]) == activity_id, "解除父级不得丢失原 activity_id"

    sub = _create_task(ctx, "PATCH-已有子任务", parent_id=top_id)
    third = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{other_id}",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={"parent_id": int(sub["id"])},
        label="PATCH 挂到已有子任务下应被拒绝",
    )
    assert third.get("msg") == "子任务不可继续拆分", f"PATCH 三层限制文案应逐字返回（实际 {third.get('msg')!r}）"
    assert _get_task(ctx, other_id).get("parent_id") is None, "失败 PATCH 不得改写 parent_id"

    missing_parent = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{other_id}",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={"parent_id": 999999},
        label="PATCH 不存在的父任务",
    )
    assert missing_parent.get("msg") == "父任务不存在", f"父任务不存在文案应逐字返回（实际 {missing_parent.get('msg')!r}）"


def test_activity_tree_skips_orphan_subtask(ctx: _Ctx) -> None:
    activity = _create_activity(ctx, "树-孤儿数据防御")
    activity_id = int(activity["id"])
    top = _create_task(ctx, "树-正常顶层", activity_id=activity_id)

    # 直接写库模拟历史脏数据：子任务的 parent_id 指向不存在的任务。
    with SessionLocal() as db:
        db.add(
            Task(
                parent_id=999999,
                activity_id=activity_id,
                title="树-孤儿子任务",
                status="verified",
                publisher_id=ctx.ids["teacher01"],
            )
        )
        db.commit()

    detail = _activity_detail(ctx, activity_id)
    assert [int(node["id"]) for node in detail["tasks"]] == [int(top["id"])], "孤儿节点不得出现在任务树根层"
    assert detail["tasks"][0]["children"] == [], "孤儿节点不得挂到任何父节点"

    progress = detail["progress"]
    assert progress["subtask_total"] == 1, f"孤儿子任务仍计入 subtask_total（实际 {progress['subtask_total']}）"
    assert progress["subtask_completed"] == 1, (
        f"孤儿子任务 verified 仍计入 subtask_completed（实际 {progress['subtask_completed']}）"
    )
    assert progress["total_tasks"] == 1, "孤儿节点不得计入顶层分母"
    assert progress["percent"] == 0, "孤儿子任务完成不得改变活动进度"


# --------------------------------------------------------------------------- #
# 8. 迁移幂等（C-MIGRATION-2@1）
# --------------------------------------------------------------------------- #
def test_migration_adds_activity_column_and_is_idempotent(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy_p1.db"
    raw = sqlite3.connect(legacy_path)
    raw.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'published',
            created_at TEXT NOT NULL
        );
        INSERT INTO tasks (parent_id, title, status, created_at)
        VALUES (NULL, '旧库独立任务', 'published', '2026-01-01 08:00:00');
        """
    )
    raw.commit()
    raw.close()

    legacy_engine = create_engine(f"sqlite:///{legacy_path.as_posix()}")
    try:
        with legacy_engine.begin() as conn:
            assert "activity_id" not in _column_names(conn, "tasks"), "前置条件：旧库 tasks 表没有 activity_id"
            _migrate(conn)
            _migrate(conn)  # 第二次执行必须幂等
            columns = _column_names(conn, "tasks")
            assert "activity_id" in columns, "迁移应补上 tasks.activity_id 列"
            column_rows = conn.exec_driver_sql("PRAGMA table_info(tasks)").fetchall()
            assert sum(1 for row in column_rows if row[1] == "activity_id") == 1, "重复迁移不得重复添加 activity_id 列"
            indexes = conn.exec_driver_sql("PRAGMA index_list(tasks)").fetchall()
            assert any(row[1] == "ix_tasks_activity_id" for row in indexes), "迁移应创建 ix_tasks_activity_id 索引"
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM tasks").scalar() == 1, "迁移不得删行或补行"
            assert conn.exec_driver_sql("SELECT activity_id FROM tasks").scalar() is None, "旧任务 activity_id 应保持 NULL"
    finally:
        legacy_engine.dispose()

    empty_engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    try:
        with empty_engine.begin() as conn:
            _migrate(conn)  # 空库无 tasks 表时不得抛错
    finally:
        empty_engine.dispose()

    with engine.connect() as conn:
        before = conn.exec_driver_sql("SELECT COUNT(*) FROM tasks").scalar()
    init_db()
    init_db()  # 当前测试库重复 init_db 必须幂等
    with engine.connect() as conn:
        assert "activity_id" in _column_names(conn, "tasks"), "当前库应有 tasks.activity_id 列"
        indexes = conn.exec_driver_sql("PRAGMA index_list(tasks)").fetchall()
        assert any(row[1] == "ix_tasks_activity_id" for row in indexes), "当前库应有 ix_tasks_activity_id 索引"
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tasks").scalar() == before, "重复 init_db 不得增删任务行"

# --------------------------------------------------------------------------- #
# 9. 有子任务的任务变更所属活动（漂移）必须被拒绝
# --------------------------------------------------------------------------- #
def _assert_activity_membership_unchanged(ctx: _Ctx, *, top_id: int, sub_id: int, source_id: int, target_id: int) -> None:
    """断言漂移请求失败后，任务与两个活动的归属完全不变。"""
    top_detail = _get_task(ctx, top_id)
    sub_detail = _get_task(ctx, sub_id)
    assert int(top_detail["activity_id"]) == source_id, (
        f"失败请求不得改写父任务 activity_id（期望 {source_id}，实际 {top_detail['activity_id']}）"
    )
    assert int(sub_detail["activity_id"]) == source_id, (
        f"失败请求不得改写子任务 activity_id（期望 {source_id}，实际 {sub_detail['activity_id']}）"
    )
    assert top_detail.get("parent_id") is None, "失败请求不得改写父任务 parent_id"
    assert int(sub_detail["parent_id"]) == top_id, "失败请求不得改写子任务 parent_id"

    source_tasks = _activity_tasks(ctx, source_id, include_sub=True)
    assert {int(item["id"]) for item in source_tasks} == {top_id, sub_id}, (
        f"原活动任务集合必须保持不变（实际 {[int(item['id']) for item in source_tasks]}）"
    )
    assert _activity_tasks(ctx, target_id, include_sub=True) == [], "目标活动不得被写入任何任务"


def test_patch_rejects_activity_drift_when_task_has_subtasks(ctx: _Ctx) -> None:
    source = _create_activity(ctx, "漂移-原活动")
    target = _create_activity(ctx, "漂移-目标活动")
    source_id = int(source["id"])
    target_id = int(target["id"])

    top = _create_task(ctx, "漂移-有子任务的任务", activity_id=source_id)
    top_id = int(top["id"])
    sub = _create_task(ctx, "漂移-子任务", parent_id=top_id)
    sub_id = int(sub["id"])

    rejected = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{top_id}",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={"activity_id": target_id},
        label="有子任务的任务变更所属活动应被拒绝",
    )
    assert rejected.get("msg") == "存在子任务的任务不可直接变更所属活动", (
        f"漂移拒绝文案应逐字返回（实际 {rejected.get('msg')!r}）"
    )
    _assert_activity_membership_unchanged(
        ctx, top_id=top_id, sub_id=sub_id, source_id=source_id, target_id=target_id
    )


def test_patch_rejects_activity_null_drift_when_task_has_subtasks(ctx: _Ctx) -> None:
    source = _create_activity(ctx, "漂移-原活动（置空）")
    target = _create_activity(ctx, "漂移-目标活动（置空）")
    source_id = int(source["id"])
    target_id = int(target["id"])

    top = _create_task(ctx, "漂移-有子任务的任务（置空）", activity_id=source_id)
    top_id = int(top["id"])
    sub = _create_task(ctx, "漂移-子任务（置空）", parent_id=top_id)
    sub_id = int(sub["id"])

    rejected = _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{top_id}",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body={"activity_id": None},
        label="有子任务的任务显式置空所属活动应被拒绝",
    )
    assert rejected.get("msg") == "存在子任务的任务不可直接变更所属活动", (
        f"显式 null 漂移的拒绝文案应逐字返回（实际 {rejected.get('msg')!r}）"
    )
    _assert_activity_membership_unchanged(
        ctx, top_id=top_id, sub_id=sub_id, source_id=source_id, target_id=target_id
    )