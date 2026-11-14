#!/usr/bin/env python
"""AIW-09 增量 r3：会话列表分页与 total 后端测试（契约 `C-AI-HISTORY@3`）。

覆盖真实 HTTP 行为：

1. ``offset`` / ``limit`` 分页按 ``updated_at DESC, id DESC`` 稳定排序，
   逐页拼接无重复、无遗漏，``total`` 为同 owner 会话总数；
2. 同一 ``updated_at`` 的多条会话按 ``id DESC`` 排出稳定顺序；
3. ``scope_type`` / ``scope_id`` 过滤语义不变，``total`` 只计该作用域；
4. 他人会话不可见，``total`` 只计本人；
5. ``offset`` 越界返回空页但仍返回 ``total``；负数 ``offset`` → 4001；
6. 未登录 → HTTP 401 + ``code=4010``。

隔离性：在导入 ``app`` 之前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立
SQLite 文件，关闭调度器并强制 ``MAAS_MOCK=1``；不触碰 ``backend/campus.db``。

可独立运行：``python -m pytest tests/backend/test_aiw09_history.py -q``。
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw09-history-"))
_TEST_DB_PATH = _TMP_DIR / "aiw09_history.db"

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
from app.models import AiConversation, AiMessage, OrgMember, Organization, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

ERR_UNAUTHORIZED = 4010
ERR_INVALID_INPUT = 4001

PASSWORD = "TestPass123!"
HISTORY_PATH = "/api/agent/conversations"

# 同秒写入组（40 条）与更早组（20 条），共 60 条本人 general 会话。
SAME_SECOND = "2032-01-01 10:00:00"
OLDER_SECOND = "2031-01-01 10:00:00"
SCOPE_OLDER = "2030-01-01 10:00:00"


@dataclass
class _Ctx:
    client: TestClient
    owner: dict[str, str]
    other: dict[str, str]
    owner_id: int
    other_id: int
    activity_id: int
    same_second_ids: list[int]
    older_ids: list[int]
    activity_ids: list[int]
    other_conversation_id: int


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


def _insert_conversation(
    user_id: int,
    title: str,
    updated_at: str,
    *,
    scope_type: str = "general",
    scope_id: int | None = None,
    message_count: int = 0,
) -> int:
    with SessionLocal() as db:
        conversation = AiConversation(
            user_id=user_id,
            title=title,
            scope_type=scope_type,
            scope_id=scope_id,
            created_at=updated_at,
            updated_at=updated_at,
        )
        db.add(conversation)
        db.flush()
        for index in range(message_count):
            db.add(
                AiMessage(
                    conversation_id=int(conversation.id),
                    role="user" if index % 2 == 0 else "assistant",
                    content=f"{title} 第 {index + 1} 条",
                    citations=[],
                    mock=1,
                )
            )
        db.commit()
        db.refresh(conversation)
        return int(conversation.id)


def _list(
    client: TestClient,
    headers: dict[str, str] | None,
    **params: int | str,
) -> tuple[int, dict]:
    response = client.get(HISTORY_PATH, params=params, headers=headers or {})
    payload = response.json()
    assert isinstance(payload, dict), f"GET {HISTORY_PATH}：响应体不是对象"
    return response.status_code, payload


def _ok_list(
    client: TestClient,
    headers: dict[str, str] | None,
    *,
    label: str = "",
    **params: int | str,
) -> dict:
    status, payload = _list(client, headers, **params)
    assert status == 200, f"{label}：期望 HTTP 200，实际 HTTP {status}"
    assert payload.get("code") == 0, f"{label}：期望 code=0，实际 {payload.get('code')}（{payload.get('msg')}）"
    data = payload.get("data")
    assert isinstance(data, dict), f"{label}：data 不是对象"
    assert isinstance(data.get("items"), list), f"{label}：items 不是列表"
    assert isinstance(data.get("total"), int), f"{label}：total 不是整数"
    return data


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        owner_id = _ensure_user("aiw09_history_owner", "AIW09 历史负责人")
        other_id = _ensure_user("aiw09_history_other", "AIW09 历史他人")
        org_id = _ensure_org("AIW09 历史组织", "aiw09-history-org", roles={owner_id: "admin"})

        owner = _login(client, "aiw09_history_owner")
        other = _login(client, "aiw09_history_other")

        response = client.post(
            "/api/activities",
            json={"title": "AIW09 历史活动", "org_id": org_id},
            headers=owner,
        )
        payload = response.json()
        assert response.status_code == 200 and payload.get("code") == 0, "创建历史活动失败"
        activity_id = int(payload["data"]["id"])

        same_second_ids = [
            _insert_conversation(owner_id, f"同秒会话 {index}", SAME_SECOND, message_count=index % 3)
            for index in range(40)
        ]
        older_ids = [
            _insert_conversation(owner_id, f"更早会话 {index}", OLDER_SECOND) for index in range(20)
        ]
        activity_ids = [
            _insert_conversation(
                owner_id,
                f"活动会话 {index}",
                SCOPE_OLDER,
                scope_type="activity",
                scope_id=activity_id,
                message_count=1,
            )
            for index in range(2)
        ]
        other_conversation_id = _insert_conversation(other_id, "他人会话", OLDER_SECOND)

        yield _Ctx(
            client=client,
            owner=owner,
            other=other,
            owner_id=owner_id,
            other_id=other_id,
            activity_id=activity_id,
            same_second_ids=same_second_ids,
            older_ids=older_ids,
            activity_ids=activity_ids,
            other_conversation_id=other_conversation_id,
        )


def test_pagination_covers_all_without_duplicates(ctx: _Ctx) -> None:
    """逐页拼接覆盖全部 62 条本人会话，无重复无遗漏，total 稳定。"""
    pages: list[list[int]] = []
    for offset in (0, 20, 40, 60):
        data = _ok_list(
            ctx.client,
            ctx.owner,
            offset=offset,
            limit=20,
            label=f"本人会话 offset={offset}",
        )
        assert data["total"] == 62, f"offset={offset}：total 应为 62，实际 {data['total']}"
        pages.append([int(item["id"]) for item in data["items"]])

    assert [len(page) for page in pages] == [20, 20, 20, 2], "分页大小不符合预期"
    merged = [conversation_id for page in pages for conversation_id in page]
    assert len(merged) == len(set(merged)) == 62, "分页结果存在重复或遗漏"
    assert set(merged) == set(ctx.same_second_ids) | set(ctx.older_ids) | set(ctx.activity_ids)

    # 同秒组按 id DESC，更早组在其后，活动作用域会话最旧排在末尾。
    assert merged[:40] == sorted(ctx.same_second_ids, reverse=True)
    assert merged[40:60] == sorted(ctx.older_ids, reverse=True)
    assert merged[60:] == sorted(ctx.activity_ids, reverse=True)


def test_same_second_order_is_stable_by_id(ctx: _Ctx) -> None:
    """同一 updated_at 的 40 条会话按 id DESC 稳定排序。"""
    data = _ok_list(ctx.client, ctx.owner, offset=0, limit=40, label="同秒组一页")
    ids = [int(item["id"]) for item in data["items"]]
    assert ids == sorted(ctx.same_second_ids, reverse=True)
    assert all(item["updated_at"] == SAME_SECOND for item in data["items"])
    assert data["total"] == 62


def test_scope_filter_keeps_total_and_page(ctx: _Ctx) -> None:
    """scope 过滤语义不变；total 只计该作用域。"""
    general = _ok_list(
        ctx.client,
        ctx.owner,
        scope_type="general",
        offset=0,
        limit=20,
        label="general 作用域第一页",
    )
    assert general["total"] == 60
    assert [int(item["id"]) for item in general["items"]] == sorted(
        ctx.same_second_ids, reverse=True
    )[:20]
    assert all(item["scope_type"] == "general" for item in general["items"])

    activity = _ok_list(
        ctx.client,
        ctx.owner,
        scope_type="activity",
        scope_id=ctx.activity_id,
        limit=20,
        label="活动作用域列表",
    )
    assert activity["total"] == 2
    assert [int(item["id"]) for item in activity["items"]] == sorted(
        ctx.activity_ids, reverse=True
    )

    second = _ok_list(
        ctx.client,
        ctx.owner,
        scope_type="activity",
        scope_id=ctx.activity_id,
        offset=1,
        limit=1,
        label="活动作用域第二页",
    )
    assert second["total"] == 2
    assert [int(item["id"]) for item in second["items"]] == [ctx.activity_ids[0]]


def test_other_user_conversations_are_invisible(ctx: _Ctx) -> None:
    """他人会话不出现在列表，total 只计本人。"""
    data = _ok_list(ctx.client, ctx.other, offset=0, limit=50, label="他人本人会话")
    assert data["total"] == 1
    assert [int(item["id"]) for item in data["items"]] == [ctx.other_conversation_id]
    assert {int(item["id"]) for item in data["items"]}.isdisjoint(
        set(ctx.same_second_ids) | set(ctx.older_ids) | set(ctx.activity_ids)
    )


def test_offset_bounds(ctx: _Ctx) -> None:
    """offset 越界返回空页但保留 total；负数 offset → 4001。"""
    beyond = _ok_list(ctx.client, ctx.owner, offset=1000, limit=20, label="offset 越界")
    assert beyond["items"] == []
    assert beyond["total"] == 62

    status, payload = _list(ctx.client, ctx.owner, offset=-1)
    assert status == 200, f"负数 offset：期望 HTTP 200，实际 {status}"
    assert payload.get("code") == ERR_INVALID_INPUT, "负数 offset：期望 code=4001"


def test_list_requires_login(ctx: _Ctx) -> None:
    """未登录 → HTTP 401 + code=4010。"""
    status, payload = _list(ctx.client, None)
    assert status == 401, f"未登录列表：期望 HTTP 401，实际 {status}"
    assert payload.get("code") == ERR_UNAUTHORIZED, "未登录列表：期望 code=4010"