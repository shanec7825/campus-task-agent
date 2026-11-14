#!/usr/bin/env python
"""AIW-09 增量 r1：会话作用域、归属与乱序归属后端测试（契约 `C-AI-SCOPE@1`）。

覆盖真实 HTTP 行为：

1. 作用域归一化：``general`` 带 ``scope_id``、活动/任务缺 ID 或非正整数一律 4001；
   列表只给 ``scope_id`` 同样 4001；
2. 新建活动 / 任务会话写入作用类型与对象 ID，列表按作用域过滤，详情返回作用域；
3. 上下文只含作用域内可见任务：活动只含该活动任务；任务含自身及同活动任务，
   不含独立任务与其他活动任务；
4. 跨账号读取 / 续写他人会话 4040，且不追加消息；
5. 无权限活动 / 任务 4040（HTTP 404），且不写入任何会话行；
6. 续写时请求作用域与会话行不一致 4001；
7. ``stream/parse`` 解析会话写入发起者；他人与无主（``user_id IS NULL``）一律 4040；
8. 撤权后活动 / 任务会话详情与续写 4040，会话行与消息保留不删。

隔离性：在导入 ``app`` 之前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立
SQLite 文件，关闭调度器并强制 ``MAAS_MOCK=1``；不触碰 ``backend/campus.db``。

可独立运行：``python -m pytest tests/backend/test_aiw09_context_scope.py -q``。
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

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw09-scope-"))
_TEST_DB_PATH = _TMP_DIR / "aiw09_scope.db"

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
from app.models import AiConversation, AiMessage, OrgMember, Organization, ParseSession, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

ERR_INVALID_INPUT = 4001
ERR_NOT_FOUND = 4040

PASSWORD = "TestPass123!"


@dataclass
class _Ctx:
    client: TestClient
    admin: dict[str, str]
    owner: dict[str, str]
    reviewer: dict[str, str]
    outsider: dict[str, str]
    ids: dict[str, int]
    org_a: int
    org_b: int
    org_c: int
    act_a: int
    act_b: int
    act_c: int
    task_a1: int
    task_a2: int
    personal_task: int
    task_b: int
    task_c: int


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


def _err(
    client: TestClient,
    method: str,
    path: str,
    *,
    code: int,
    headers: dict[str, str] | None = None,
    body: Any = None,
    status: int,
    label: str = "",
) -> dict:
    actual_status, payload = _payload(client, method, path, headers=headers, body=body)
    assert actual_status == status, f"{label}：期望 HTTP {status}，实际 {actual_status}"
    assert payload.get("code") == code, f"{label}：期望 code={code}，实际 {payload.get('code')}"
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


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        admin_id = _ensure_user("aiw09_admin", "AIW09 管理员")
        owner_id = _ensure_user("aiw09_owner", "AIW09 活动负责人")
        reviewer_id = _ensure_user("aiw09_reviewer", "AIW09 组织管理员")
        outsider_id = _ensure_user("aiw09_outsider", "AIW09 外部成员")

        org_a = _ensure_org("AIW09 组织 A", "aiw09-org-a", roles={admin_id: "admin"})
        org_b = _ensure_org("AIW09 组织 B", "aiw09-org-b", roles={outsider_id: "admin"})
        org_c = _ensure_org(
            "AIW09 组织 C",
            "aiw09-org-c",
            roles={owner_id: "collaborator", reviewer_id: "admin"},
        )

        admin = _login(client, "aiw09_admin")
        owner = _login(client, "aiw09_owner")
        reviewer = _login(client, "aiw09_reviewer")
        outsider = _login(client, "aiw09_outsider")

        act_a = _ok(
            client,
            "POST",
            "/api/activities",
            headers=admin,
            body={"title": "AIW09 活动 A", "org_id": org_a},
            label="创建组织 A 活动",
        )
        act_b = _ok(
            client,
            "POST",
            "/api/activities",
            headers=outsider,
            body={"title": "AIW09 活动 B", "org_id": org_b},
            label="创建组织 B 活动",
        )
        act_c = _ok(
            client,
            "POST",
            "/api/activities",
            headers=owner,
            body={"title": "AIW09 活动 C", "org_id": org_c},
            label="创建组织 C 活动",
        )

        task_a1 = _ok(
            client,
            "POST",
            "/api/tasks",
            headers=admin,
            body={"title": "AIW09 活动 A 任务一", "activity_id": int(act_a["id"])},
            label="创建活动 A 任务一",
        )
        task_a2 = _ok(
            client,
            "POST",
            "/api/tasks",
            headers=admin,
            body={"title": "AIW09 活动 A 任务二", "activity_id": int(act_a["id"])},
            label="创建活动 A 任务二",
        )
        personal_task = _ok(
            client,
            "POST",
            "/api/tasks",
            headers=admin,
            body={"title": "AIW09 独立任务", "deadline": "2099-12-31 23:59:59"},
            label="创建独立任务",
        )
        task_b = _ok(
            client,
            "POST",
            "/api/tasks",
            headers=outsider,
            body={"title": "AIW09 活动 B 任务", "activity_id": int(act_b["id"])},
            label="创建活动 B 任务",
        )
        task_c = _ok(
            client,
            "POST",
            "/api/tasks",
            headers=owner,
            body={"title": "AIW09 活动 C 任务", "activity_id": int(act_c["id"])},
            label="创建活动 C 任务",
        )

        yield _Ctx(
            client=client,
            admin=admin,
            owner=owner,
            reviewer=reviewer,
            outsider=outsider,
            ids={
                "admin": admin_id,
                "owner": owner_id,
                "reviewer": reviewer_id,
                "outsider": outsider_id,
            },
            org_a=org_a,
            org_b=org_b,
            org_c=org_c,
            act_a=int(act_a["id"]),
            act_b=int(act_b["id"]),
            act_c=int(act_c["id"]),
            task_a1=int(task_a1["id"]),
            task_a2=int(task_a2["id"]),
            personal_task=int(personal_task["id"]),
            task_b=int(task_b["id"]),
            task_c=int(task_c["id"]),
        )


def test_scope_normalization_is_4001(ctx: _Ctx) -> None:
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "通用会话不应带对象", "scope_type": "general", "scope_id": ctx.act_a},
        code=ERR_INVALID_INPUT,
        status=200,
        label="general 带 scope_id",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "活动会话缺对象", "scope_type": "activity"},
        code=ERR_INVALID_INPUT,
        status=200,
        label="活动缺 scope_id",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "任务 ID 非正", "scope_type": "task", "scope_id": 0},
        code=ERR_INVALID_INPUT,
        status=200,
        label="任务 scope_id 为 0",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "任务 ID 为负", "scope_type": "task", "scope_id": -5},
        code=ERR_INVALID_INPUT,
        status=200,
        label="任务 scope_id 为负",
    )
    _err(
        ctx.client,
        "GET",
        "/api/agent/conversations?scope_id=3",
        headers=ctx.admin,
        code=ERR_INVALID_INPUT,
        status=200,
        label="列表只给 scope_id",
    )
    _err(
        ctx.client,
        "GET",
        f"/api/agent/conversations?scope_type=general&scope_id={ctx.act_a}",
        headers=ctx.admin,
        code=ERR_INVALID_INPUT,
        status=200,
        label="列表 general 带 scope_id",
    )


def test_scoped_chat_persists_scope_and_filters_list(ctx: _Ctx) -> None:
    general = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "通用目标有哪些事务？"},
        label="默认通用会话",
    )
    activity = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={
            "message": "当前目标有哪些事务？",
            "scope_type": "activity",
            "scope_id": ctx.act_a,
        },
        label="活动会话",
    )
    task = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={
            "message": "当前目标有哪些事务？",
            "scope_type": "task",
            "scope_id": ctx.task_a1,
        },
        label="任务会话",
    )
    general_id = int(general["conversation_id"])
    activity_id = int(activity["conversation_id"])
    task_id = int(task["conversation_id"])

    general_detail = _ok(
        ctx.client,
        "GET",
        f"/api/agent/conversations/{general_id}",
        headers=ctx.admin,
        label="通用会话详情",
    )
    assert general_detail["conversation"]["scope_type"] == "general"
    assert general_detail["conversation"]["scope_id"] is None

    activity_detail = _ok(
        ctx.client,
        "GET",
        f"/api/agent/conversations/{activity_id}",
        headers=ctx.admin,
        label="活动会话详情",
    )
    assert activity_detail["conversation"]["scope_type"] == "activity"
    assert int(activity_detail["conversation"]["scope_id"]) == ctx.act_a

    task_detail = _ok(
        ctx.client,
        "GET",
        f"/api/agent/conversations/{task_id}",
        headers=ctx.admin,
        label="任务会话详情",
    )
    assert task_detail["conversation"]["scope_type"] == "task"
    assert int(task_detail["conversation"]["scope_id"]) == ctx.task_a1

    general_list = _ok(
        ctx.client,
        "GET",
        "/api/agent/conversations?scope_type=general",
        headers=ctx.admin,
        label="通用会话列表",
    )
    general_ids = {int(item["id"]) for item in general_list["items"]}
    assert general_id in general_ids
    assert activity_id not in general_ids and task_id not in general_ids

    activity_list = _ok(
        ctx.client,
        "GET",
        f"/api/agent/conversations?scope_type=activity&scope_id={ctx.act_a}",
        headers=ctx.admin,
        label="活动会话列表",
    )
    activity_ids = {int(item["id"]) for item in activity_list["items"]}
    assert activity_ids == {activity_id}
    assert activity_list["items"][0]["scope_type"] == "activity"

    task_list = _ok(
        ctx.client,
        "GET",
        f"/api/agent/conversations?scope_type=task&scope_id={ctx.task_a1}",
        headers=ctx.admin,
        label="任务会话列表",
    )
    assert {int(item["id"]) for item in task_list["items"]} == {task_id}

    all_list = _ok(
        ctx.client,
        "GET",
        "/api/agent/conversations",
        headers=ctx.admin,
        label="不带作用域的会话列表",
    )
    all_ids = {int(item["id"]) for item in all_list["items"]}
    assert {general_id, activity_id, task_id} <= all_ids, "不带作用域应返回本人全部会话"


def test_scope_context_contains_only_target_tasks(ctx: _Ctx) -> None:
    activity = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={
            "message": "当前目标有哪些事务？",
            "scope_type": "activity",
            "scope_id": ctx.act_a,
        },
        label="活动上下文问答",
    )
    activity_cited = {int(item["id"]) for item in activity["assistant_message"]["citations"]}
    assert activity_cited == {ctx.task_a1, ctx.task_a2}, (
        f"活动上下文只应含活动 A 任务（实际 {activity_cited}）"
    )
    activity_content = activity["assistant_message"]["content"]
    assert "AIW09 独立任务" not in activity_content, "活动上下文不得含独立任务"
    assert "AIW09 活动 B 任务" not in activity_content, "活动上下文不得含其他活动任务"

    task = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={
            "message": "当前目标有哪些事务？",
            "scope_type": "task",
            "scope_id": ctx.task_a1,
        },
        label="任务上下文问答",
    )
    task_cited = {int(item["id"]) for item in task["assistant_message"]["citations"]}
    assert task_cited == {ctx.task_a1, ctx.task_a2}, (
        f"任务上下文应含该任务及同活动可见任务（实际 {task_cited}）"
    )
    task_content = task["assistant_message"]["content"]
    assert "AIW09 独立任务" not in task_content, "任务上下文不得含独立任务"
    assert "AIW09 活动 B 任务" not in task_content, "任务上下文不得含其他活动任务"


def test_cross_account_conversation_is_4040(ctx: _Ctx) -> None:
    created = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "跨账号隔离测试"},
        label="管理员创建隔离测试会话",
    )
    conversation_id = int(created["conversation_id"])

    _err(
        ctx.client,
        "GET",
        f"/api/agent/conversations/{conversation_id}",
        headers=ctx.outsider,
        code=ERR_NOT_FOUND,
        status=404,
        label="他人读取会话详情",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.outsider,
        body={"conversation_id": conversation_id, "message": "续写他人会话"},
        code=ERR_NOT_FOUND,
        status=404,
        label="他人续写会话",
    )

    with SessionLocal() as db:
        assert db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).count() == 2, (
            "跨账号续写失败不应写入消息"
        )


def test_unviewable_scope_is_4040_without_rows(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        before_conversations = db.query(AiConversation).count()
        before_messages = db.query(AiMessage).count()

    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={
            "message": "不可见活动",
            "scope_type": "activity",
            "scope_id": ctx.act_c,
        },
        code=ERR_NOT_FOUND,
        status=404,
        label="无权限活动",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "不可见任务", "scope_type": "task", "scope_id": ctx.task_c},
        code=ERR_NOT_FOUND,
        status=404,
        label="无权限任务",
    )
    _err(
        ctx.client,
        "GET",
        f"/api/agent/conversations?scope_type=activity&scope_id={ctx.act_c}",
        headers=ctx.admin,
        code=ERR_NOT_FOUND,
        status=404,
        label="无权限活动列表",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "不存在的活动", "scope_type": "activity", "scope_id": 999999},
        code=ERR_NOT_FOUND,
        status=404,
        label="不存在的活动对象",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "不存在的任务", "scope_type": "task", "scope_id": 999999},
        code=ERR_NOT_FOUND,
        status=404,
        label="不存在的任务对象",
    )
    _err(
        ctx.client,
        "GET",
        "/api/agent/conversations?scope_type=task&scope_id=999999",
        headers=ctx.admin,
        code=ERR_NOT_FOUND,
        status=404,
        label="不存在的任务对象列表",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.outsider,
        body={"message": "跨组织活动", "scope_type": "activity", "scope_id": ctx.act_a},
        code=ERR_NOT_FOUND,
        status=404,
        label="跨组织活动新建会话",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.outsider,
        body={"message": "跨组织任务", "scope_type": "task", "scope_id": ctx.task_a1},
        code=ERR_NOT_FOUND,
        status=404,
        label="跨组织任务新建会话",
    )

    with SessionLocal() as db:
        assert db.query(AiConversation).count() == before_conversations, "作用域校验失败不得写会话"
        assert db.query(AiMessage).count() == before_messages, "作用域校验失败不得写消息"


def test_scope_mismatch_on_continuation_is_4001(ctx: _Ctx) -> None:
    created = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={
            "message": "作用域一致性初始会话",
            "scope_type": "activity",
            "scope_id": ctx.act_a,
        },
        label="创建活动作用域会话",
    )
    conversation_id = int(created["conversation_id"])

    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"conversation_id": conversation_id, "message": "按通用作用域续写"},
        code=ERR_INVALID_INPUT,
        status=200,
        label="续写作用域不一致（默认 general）",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={
            "conversation_id": conversation_id,
            "message": "换任务作用域续写",
            "scope_type": "task",
            "scope_id": ctx.task_a1,
        },
        code=ERR_INVALID_INPUT,
        status=200,
        label="续写作用域不一致（task）",
    )

    continued = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={
            "conversation_id": conversation_id,
            "message": "按原作用域续写",
            "scope_type": "activity",
            "scope_id": ctx.act_a,
        },
        label="同作用域续写",
    )
    assert int(continued["conversation_id"]) == conversation_id

    with SessionLocal() as db:
        assert db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).count() == 4, (
            "两次失败续写不应追加消息，仅成功续写追加 2 条"
        )


def test_parse_session_owner_guard(ctx: _Ctx) -> None:
    session_id = "aiw09-parse-owner"
    _ok(
        ctx.client,
        "POST",
        "/api/agent/stream/parse",
        headers=ctx.admin,
        body={"session_id": session_id, "chunk": "第一阶段", "is_final": False},
        label="管理员创建解析会话",
    )
    with SessionLocal() as db:
        row = db.get(ParseSession, session_id)
        assert row is not None and row.user_id == ctx.ids["admin"], "解析会话应写入发起者"

    _err(
        ctx.client,
        "POST",
        "/api/agent/stream/parse",
        headers=ctx.outsider,
        body={"session_id": session_id, "chunk": "他人追加", "is_final": False},
        code=ERR_NOT_FOUND,
        status=404,
        label="他人续写解析会话",
    )
    with SessionLocal() as db:
        row = db.get(ParseSession, session_id)
        assert row is not None and row.accumulated_text == "第一阶段", "他人请求不得改写解析会话"

    _ok(
        ctx.client,
        "POST",
        "/api/agent/stream/parse",
        headers=ctx.admin,
        body={"session_id": session_id, "chunk": "第二阶段", "is_final": False},
        label="发起者继续解析会话",
    )

    with SessionLocal() as db:
        row = db.get(ParseSession, session_id)
        assert row is not None
        row.user_id = None
        db.commit()

    _err(
        ctx.client,
        "POST",
        "/api/agent/stream/parse",
        headers=ctx.admin,
        body={"session_id": session_id, "chunk": "无主追加", "is_final": False},
        code=ERR_NOT_FOUND,
        status=404,
        label="无主解析会话拒绝续写",
    )


def test_revoked_permission_keeps_rows_but_rejects(ctx: _Ctx) -> None:
    task_conv = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.reviewer,
        body={"message": "撤权前任务会话", "scope_type": "task", "scope_id": ctx.task_c},
        label="管理员创建任务作用域会话",
    )
    activity_conv = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.reviewer,
        body={"message": "撤权前活动会话", "scope_type": "activity", "scope_id": ctx.act_c},
        label="管理员创建活动作用域会话",
    )
    task_conversation_id = int(task_conv["conversation_id"])
    activity_conversation_id = int(activity_conv["conversation_id"])

    with SessionLocal() as db:
        before_messages = db.query(AiMessage).filter(
            AiMessage.conversation_id.in_([task_conversation_id, activity_conversation_id])
        ).count()
        db.query(OrgMember).filter(
            OrgMember.org_id == ctx.org_c,
            OrgMember.user_id == ctx.ids["reviewer"],
        ).delete(synchronize_session=False)
        db.commit()

    try:
        _err(
            ctx.client,
            "GET",
            f"/api/agent/conversations/{task_conversation_id}",
            headers=ctx.reviewer,
            code=ERR_NOT_FOUND,
            status=404,
            label="撤权后任务会话详情",
        )
        _err(
            ctx.client,
            "GET",
            f"/api/agent/conversations/{activity_conversation_id}",
            headers=ctx.reviewer,
            code=ERR_NOT_FOUND,
            status=404,
            label="撤权后活动会话详情",
        )
        _err(
            ctx.client,
            "POST",
            "/api/agent/chat",
            headers=ctx.reviewer,
            body={
                "conversation_id": task_conversation_id,
                "message": "撤权后续写",
                "scope_type": "task",
                "scope_id": ctx.task_c,
            },
            code=ERR_NOT_FOUND,
            status=404,
            label="撤权后续写任务会话",
        )

        revoked_list = _ok(
            ctx.client,
            "GET",
            "/api/agent/conversations",
            headers=ctx.reviewer,
            label="撤权后不带作用域的列表",
        )
        revoked_ids = {int(item["id"]) for item in revoked_list["items"]}
        assert task_conversation_id not in revoked_ids, "撤权后列表不得出现该任务会话（行仍保留）"
        assert activity_conversation_id not in revoked_ids, "撤权后列表不得出现该活动会话（行仍保留）"

        with SessionLocal() as db:
            assert db.get(AiConversation, task_conversation_id) is not None, "撤权不删除会话行"
            assert db.get(AiConversation, activity_conversation_id) is not None, "撤权不删除活动会话行"
            assert db.query(AiMessage).filter(
                AiMessage.conversation_id.in_([task_conversation_id, activity_conversation_id])
            ).count() == before_messages, "撤权后的拒绝不追加消息"
    finally:
        # 恢复组织成员关系，避免撤权状态污染后续用例。
        with SessionLocal() as db:
            restored = (
                db.query(OrgMember)
                .filter(OrgMember.org_id == ctx.org_c, OrgMember.user_id == ctx.ids["reviewer"])
                .first()
            )
            if restored is None:
                db.add(
                    OrgMember(
                        org_id=ctx.org_c,
                        user_id=ctx.ids["reviewer"],
                        role="admin",
                        status="active",
                    )
                )
            else:
                restored.role = "admin"
                restored.status = "active"
            db.commit()