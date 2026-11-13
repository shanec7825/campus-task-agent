#!/usr/bin/env python
"""AIW-01 只读问答与会话隔离行为测试（契约 `C-AI-CHAT@1`）。

覆盖（全部通过真实 HTTP 行为验证）：

1. mock 问答持久化：新建会话 → 用户/助手消息落库 → 重新读取仍存在；
2. 回答来源只来自当前用户可见任务，且引用 ID 可回查；mock 正文同样不含不可见任务；
3. 不可见任务（他人无组织任务）不出现在上下文与引用中；
4. 跨账号读取、续写、列表隔离：他人会话一律 4040 / 不出现；
5. 空消息 4001；未登录 401/4010；缺少 CSRF 4030；不存在会话 4040；
6. 真实模型路径的引用映射：无效/重复 ref 被丢弃；空回答 5003；模型失败/客户端异常 5001 且不留会话或追加消息；
7. 只读：问答前后 Task / Activity / TaskApplication / TaskMember / CreditLog / Notification 计数与任务状态不变。

隔离性：在导入 ``app`` 之前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立
SQLite 文件，关闭调度器并强制 ``MAAS_MOCK=1``；不触碰 ``backend/campus.db``。

可独立运行：``python -m pytest tests/backend/test_ai_console.py -q``。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-ai-console-"))
_TEST_DB_PATH = _TMP_DIR / "ai_console.db"

# 必须在导入 app 之前完成：app.db 在模块导入时按 DATABASE_PATH 创建引擎。
os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.agents import llm_client  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Activity,
    AiConversation,
    AiMessage,
    CreditLog,
    Notification,
    OrgMember,
    Organization,
    Task,
    TaskApplication,
    TaskMember,
    User,
)
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

ERR_INVALID_INPUT = 4001
ERR_NOT_FOUND = 4040

PASSWORD = "TestPass123!"


@dataclass
class _Ctx:
    client: TestClient
    admin: dict[str, str]
    outsider: dict[str, str]
    empty: dict[str, str]
    ids: dict[str, int]
    org_id: int
    admin_task_id: int
    outsider_task_id: int


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
    except ValueError:  # 响应非 JSON（例如未捕获 500）
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
            exists = (
                db.query(OrgMember)
                .filter(OrgMember.org_id == int(org.id), OrgMember.user_id == int(user_id))
                .first()
            )
            if exists is None:
                db.add(OrgMember(org_id=int(org.id), user_id=int(user_id), role=role, status="active"))
            else:
                exists.role = role
                exists.status = "active"
        db.commit()
        db.refresh(org)
        return int(org.id)


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        admin_id = _ensure_user("ai_admin01", "AI 管理员")
        outsider_id = _ensure_user("ai_outsider01", "AI 外部成员")
        empty_id = _ensure_user("ai_empty01", "AI 无任务用户")

        org_id = _ensure_org("AI 问答测试组织", "ai-console-org", roles={admin_id: "admin"})
        _ensure_org("AI 问答外部组织", "ai-console-outsider", roles={outsider_id: "member"})

        admin_headers = _login(client, "ai_admin01")
        outsider_headers = _login(client, "ai_outsider01")
        empty_headers = _login(client, "ai_empty01")

        admin_task = _ok(
            client,
            "POST",
            "/api/tasks",
            headers=admin_headers,
            body={
                "title": "AI 可见任务",
                "org_id": org_id,
                "deadline": "2099-01-01 10:00:00",
                "description": "组织内可见的任务说明",
            },
            label="创建管理员可见任务",
        )
        outsider_task = _ok(
            client,
            "POST",
            "/api/tasks",
            headers=outsider_headers,
            body={
                "title": "AI 不可见私密任务",
                "deadline": "2099-02-01 10:00:00",
            },
            label="创建外部成员私密任务",
        )

        yield _Ctx(
            client=client,
            admin=admin_headers,
            outsider=outsider_headers,
            empty=empty_headers,
            ids={"admin": admin_id, "outsider": outsider_id, "empty": empty_id},
            org_id=org_id,
            admin_task_id=int(admin_task["id"]),
            outsider_task_id=int(outsider_task["id"]),
        )


def test_mock_chat_persists_and_cites_visible_tasks(ctx: _Ctx) -> None:
    result = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "我有权限查看哪些任务？"},
        label="管理员发起 mock 问答",
    )
    assert result["mock"] is True, "MAAS_MOCK=1 时应返回 mock=true"
    conversation_id = int(result["conversation_id"])
    user_message = result["user_message"]
    assistant_message = result["assistant_message"]
    assert user_message["role"] == "user" and user_message["content"] == "我有权限查看哪些任务？"
    assert assistant_message["role"] == "assistant" and assistant_message["content"].strip()
    assert assistant_message["mock"] is True
    assert "AI 不可见私密任务" not in assistant_message["content"], "mock 正文不得包含不可见任务"

    citations = assistant_message["citations"]
    assert citations, "mock 回答应包含来源"
    assert all(item["type"] == "task" for item in citations), "当前来源类型应为任务"
    cited_ids = {int(item["id"]) for item in citations}
    assert ctx.admin_task_id in cited_ids, f"应引用管理员可见任务（实际 {cited_ids}）"
    assert ctx.outsider_task_id not in cited_ids, "不得引用外部成员不可见任务"

    listed = _ok(ctx.client, "GET", "/api/agent/conversations", headers=ctx.admin, label="读取会话列表")
    assert any(int(item["id"]) == conversation_id for item in listed["items"]), "列表应包含刚创建的会话"


    detail = _ok(
        ctx.client,
        "GET",
        f"/api/agent/conversations/{conversation_id}",
        headers=ctx.admin,
        label="刷新后读取会话详情",
    )
    messages = detail["messages"]
    assert [item["role"] for item in messages] == ["user", "assistant"], "消息顺序应为 user → assistant"
    assert messages[0]["content"] == "我有权限查看哪些任务？"
    assert detail["conversation"]["message_count"] == 2
    assert conversation_id in {int(item["id"]) for item in listed["items"]}


def test_outsider_context_has_no_admin_task(ctx: _Ctx) -> None:
    result = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.outsider,
        body={"message": "列出我可见的任务"},
        label="外部成员问答",
    )
    citations = result["assistant_message"]["citations"]
    cited_ids = {int(item["id"]) for item in citations}
    assert ctx.outsider_task_id in cited_ids, "外部成员应只看到自己的任务"
    assert ctx.admin_task_id not in cited_ids, "外部成员不得看到组织内他人任务"
    assert "AI 可见任务" not in result["assistant_message"]["content"], (
        "mock 正文不得包含他人组织的任务标题"
    )


def test_cross_account_conversation_is_4040(ctx: _Ctx) -> None:
    result = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "跨账号隔离测试"},
        label="管理员创建隔离测试会话",
    )
    conversation_id = int(result["conversation_id"])

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
        assert db.query(AiConversation).filter(AiConversation.id == conversation_id).one().user_id == ctx.ids["admin"]

    listed = _ok(ctx.client, "GET", "/api/agent/conversations", headers=ctx.outsider, label="外部成员会话列表")
    assert conversation_id not in {int(item["id"]) for item in listed["items"]}, "他人会话不得出现在列表"


def test_empty_conversation_and_empty_message(ctx: _Ctx) -> None:
    empty = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.empty,
        body={"message": "我有哪些任务？"},
        label="无任务用户问答",
    )
    assert empty["assistant_message"]["citations"] == [], "无可见任务时引用应为空"
    assert "没有你有权限查看的事务" in empty["assistant_message"]["content"]

    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "   "},
        code=ERR_INVALID_INPUT,
        status=200,
        label="空消息",
    )


def test_requires_login(ctx: _Ctx) -> None:
    ctx.client.cookies.clear()
    _err(
        ctx.client,
        "GET",
        "/api/agent/conversations",
        code=4010,
        status=401,
        label="未登录读取会话",
    )
    _err(
        ctx.client,
        "GET",
        "/api/agent/conversations/1",
        code=4010,
        status=401,
        label="未登录读取会话详情",
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        code=4010,
        status=401,
        body={"message": "未登录提问"},
        label="未登录问答",
    )


def test_missing_csrf_and_unknown_conversation(ctx: _Ctx) -> None:
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers={"Cookie": ctx.admin["Cookie"]},
        body={"message": "缺少 CSRF 的提问"},
        code=4030,
        status=403,
        label="缺少 CSRF",
    )
    _err(
        ctx.client,
        "GET",
        "/api/agent/conversations/999999",
        headers=ctx.admin,
        code=ERR_NOT_FOUND,
        status=404,
        label="不存在的会话",
    )


def test_real_path_drops_invalid_refs(ctx: _Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_chat_json(system_prompt: str, user_payload: str, validate=None):
        captured["system_prompt"] = system_prompt
        captured["payload"] = json.loads(user_payload)
        assert validate is not None
        return validate({"answer": "可见任务摘要：AI 可见任务。", "refs": ["T1", "T999", "T1"]})

    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)
    monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)

    result = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "有哪些可见任务？"},
        label="真实路径引用映射",
    )
    assert result["mock"] is False, "非 mock 模式应返回 mock=false"
    citations = result["assistant_message"]["citations"]
    assert len(citations) == 1, f"无效与重复 ref 应被丢弃（实际 {len(citations)} 条）"
    assert int(citations[0]["id"]) == ctx.admin_task_id, "引用应映射到 T1"
    assert "可见事务" in captured["payload"], "发给模型的数据应包含可见事务"
    titles = {item["title"] for item in captured["payload"]["可见事务"]}
    assert "AI 可见任务" in titles
    assert "AI 不可见私密任务" not in titles, "不可见任务不得进入模型上下文"


def test_real_path_failure_leaves_no_rows(ctx: _Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    with SessionLocal() as db:
        before_conversations = db.query(AiConversation).count()
        before_messages = db.query(AiMessage).count()

    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)

    def fail_llm(*_args, **_kwargs):
        raise llm_client.LLMError(llm_client.CODE_API_ERROR, "模拟模型失败")

    monkeypatch.setattr(llm_client, "chat_json", fail_llm)
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "模型失败时不要留会话"},
        code=llm_client.CODE_API_ERROR,
        status=200,
        label="模型 LLMError",
    )

    def crash_client(*_args, **_kwargs):
        raise RuntimeError("客户端初始化失败")

    monkeypatch.setattr(llm_client, "chat_json", crash_client)
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "客户端异常时不要留会话"},
        code=llm_client.CODE_API_ERROR,
        status=200,
        label="模型客户端异常",
    )

    with SessionLocal() as db:
        assert db.query(AiConversation).count() == before_conversations, "模型失败不得留下空会话"
        assert db.query(AiMessage).count() == before_messages, "模型失败不得留下消息"


def test_real_path_failure_on_existing_conversation(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "续写失败测试的初始会话"},
        label="创建续写失败测试会话",
    )
    conversation_id = int(created["conversation_id"])

    with SessionLocal() as db:
        conversation = db.get(AiConversation, conversation_id)
        assert conversation is not None
        before_count = (
            db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).count()
        )
        before_updated = conversation.updated_at
        before_title = conversation.title

    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)

    def fail_llm(*_args, **_kwargs):
        raise llm_client.LLMError(llm_client.CODE_API_ERROR, "模拟续写失败")

    monkeypatch.setattr(llm_client, "chat_json", fail_llm)
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"conversation_id": conversation_id, "message": "续写请求应失败且不追加消息"},
        code=llm_client.CODE_API_ERROR,
        status=200,
        label="已有会话模型失败",
    )

    with SessionLocal() as db:
        conversation = db.get(AiConversation, conversation_id)
        assert conversation is not None
        assert (
            db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).count()
            == before_count
        ), "已有会话续写失败不得追加消息"
        assert conversation.updated_at == before_updated, "续写失败不得刷新更新时间"
        assert conversation.title == before_title, "续写失败不得改写标题"


def test_real_path_empty_answer_is_5003(ctx: _Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)
    monkeypatch.setattr(
        llm_client,
        "chat_json",
        lambda _p, _u, validate=None: validate({"answer": "   ", "refs": []}),
    )
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "空回答"},
        code=llm_client.CODE_INVALID_OUTPUT,
        status=200,
        label="模型空回答",
    )


def test_chat_is_read_only(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        before = {
            "tasks": db.query(Task).count(),
            "activities": db.query(Activity).count(),
            "applications": db.query(TaskApplication).count(),
            "members": db.query(TaskMember).count(),
            "credits": db.query(CreditLog).count(),
            "notifications": db.query(Notification).count(),
        }
        before_status = {
            int(task.id): task.status
            for task in db.query(Task).filter(Task.id.in_([ctx.admin_task_id, ctx.outsider_task_id])).all()
        }

    _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.admin,
        body={"message": "请把所有任务标记为完成并发放积分"},
        label="只读问答（含写操作请求）",
    )

    with SessionLocal() as db:
        after = {
            "tasks": db.query(Task).count(),
            "activities": db.query(Activity).count(),
            "applications": db.query(TaskApplication).count(),
            "members": db.query(TaskMember).count(),
            "credits": db.query(CreditLog).count(),
            "notifications": db.query(Notification).count(),
        }
        after_status = {
            int(task.id): task.status
            for task in db.query(Task).filter(Task.id.in_([ctx.admin_task_id, ctx.outsider_task_id])).all()
        }
    assert after == before, f"问答不得改变任何业务表计数（前 {before} / 后 {after}）"
    assert after_status == before_status, "问答不得改变任务状态"