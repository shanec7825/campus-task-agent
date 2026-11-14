#!/usr/bin/env python
"""S5 AI 任务树草案接口测试（契约 `C-AI-DRAFT@1`）。

覆盖范围：

1. mock 模式下返回确定性 3 任务树与完整字段；
2. 检索范围限定可管理组织：显式 ``org_id`` 只检索该组织，未提供时只检索
   ``admin|collaborator`` 组织；无可管理组织 → 4030（学生不可用）；
3. 无开放资料的可管理组织仍可生成（``sources=[]``）；
4. ``org_id`` 不存在 / 无权管理 → 4040 / 4030，未登录 → 4010；
5. 草案接口不写任何活动 / 任务 / 资料行；
6. 真实模型输出不合法 → 5030，真实分支每用户限流 → 4290，mock 不受限；
7. 草案结构校验：重复 key、依赖成环、跨层级依赖、多层父任务被丢弃并记 warning，
   保留的任务可直接通过整批发布校验。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH``、``ORG_LIBRARY_UPLOAD_ROOT``、
``MAAS_MOCK=1``、``MAAS_API_KEY=''``、``RUN_SCHEDULER=0``；不触碰 ``backend/campus.db``
与 ``backend/uploads``，不产生真实模型调用。

可独立运行：``python -m pytest tests/backend/test_v1_task_draft.py -q``。
"""

from __future__ import annotations

import base64
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-v1-task-draft-"))
_TEST_DB_PATH = _TMP_DIR / "task_draft.db"
_UPLOAD_ROOT = _TMP_DIR / "org-uploads"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["ORG_LIBRARY_UPLOAD_ROOT"] = str(_UPLOAD_ROOT)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.agents import llm_client, prompts  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Activity, OrgMember, OrgResource, Organization, Task, User  # noqa: E402
from app.schemas import ActivityBatchTaskDraft  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import activity_service, task_draft_service  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

PASSWORD = "TestPass123!"
ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040
ERR_UNAUTHORIZED = 4010
ERR_TOO_MANY_REQUESTS = 4290
ERR_INVALID_OUTPUT = 5030

OPEN_TEXT = "秋季招聘会任务树需要包含物资准备、现场布置与志愿者排班，并明确前置依赖。"
CLOSED_TEXT = "秋季招聘会内部预算与审批口径，仅供辅导员内部使用。"
FOREIGN_TEXT = "秋季招聘会外部资料，用于跨组织检索隔离验证。"
DRAFT_ITEM_KEYS = {"key", "title", "sop_guide", "deadline", "depends_on_keys", "parent_key"}


@dataclass
class _Ctx:
    client: TestClient
    admin: dict[str, str]
    student: dict[str, str]
    other_admin: dict[str, str]
    multi_admin: dict[str, str]
    bare: dict[str, str]
    org_id: int
    other_org_id: int
    empty_org_id: int
    open_resource_id: int
    closed_resource_id: int
    foreign_resource_id: int
    activity_id: int
    task_id: int


# --------------------------------------------------------------------------- #
# HTTP / 数据辅助
# --------------------------------------------------------------------------- #
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
        parsed = response.json()
    except ValueError:  # pragma: no cover - 非 JSON 说明发生未捕获异常
        raise AssertionError(f"{method} {path}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert isinstance(parsed, dict), f"{method} {path}：响应体不是对象"
    return response.status_code, parsed


def _ok(
    client: TestClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    label: str = "",
) -> dict:
    status, parsed = _payload(client, method, path, headers=headers, body=body)
    assert status == 200, f"{label}：期望 HTTP 200，实际 HTTP {status}（{parsed.get('msg')}）"
    assert parsed.get("code") == 0, (
        f"{label}：期望 code=0，实际 code={parsed.get('code')}（msg={parsed.get('msg')}）"
    )
    data = parsed.get("data")
    assert isinstance(data, dict), f"{label}：data 不是对象（{type(data).__name__}）"
    return data


def _err(
    client: TestClient,
    method: str,
    path: str,
    *,
    code: int,
    status: int = 200,
    headers: dict[str, str] | None = None,
    body: Any = None,
    label: str = "",
) -> dict:
    actual_status, parsed = _payload(client, method, path, headers=headers, body=body)
    assert parsed.get("code") == code, (
        f"{label}：期望 code={code}，实际 code={parsed.get('code')}（msg={parsed.get('msg')}）"
    )
    assert actual_status == status, f"{label}：期望 HTTP {status}，实际 HTTP {actual_status}"
    return parsed


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
    parsed = response.json()
    assert response.status_code == 200 and parsed.get("code") == 0, f"登录 {username} 失败"
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


def _upload_resource(
    client: TestClient,
    headers: dict[str, str],
    org_id: int,
    title: str,
    text: str,
) -> int:
    data = text.encode("utf-8")
    body = {
        "org_id": org_id,
        "title": title,
        "summary": f"{title} 简介",
        "file": {
            "name": "draft-material.txt",
            "mime": "text/plain",
            "size": len(data),
            "data_base64": base64.b64encode(data).decode("ascii"),
        },
    }
    created = _ok(client, "POST", "/api/org-resources", headers=headers, body=body, label=f"上传「{title}」")
    return int(created["id"])


def _open_resource(client: TestClient, headers: dict[str, str], resource_id: int) -> None:
    _ok(
        client,
        "PATCH",
        f"/api/org-resources/{resource_id}",
        headers=headers,
        body={"allow_student_ai": True},
        label=f"开启资料 {resource_id}",
    )


def _draft(
    client: TestClient,
    headers: dict[str, str] | None,
    body: dict,
    label: str,
) -> dict:
    return _ok(client, "POST", "/api/ai/task-draft", headers=headers, body=body, label=label)


def _row_counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(Activity).count(),
            db.query(Task).count(),
            db.query(OrgResource).count(),
        )


def _assert_publishable(tasks: list[dict]) -> None:
    """留下的草案必须能直接通过整批发布的任务级校验。"""
    drafts = [
        ActivityBatchTaskDraft(
            key=item["key"],
            title=item["title"],
            parent_key=item["parent_key"],
            depends_on_keys=list(item["depends_on_keys"]),
        )
        for item in tasks
    ]
    activity_service._validate_batch_drafts(drafts, [draft.key for draft in drafts])


def _patch_real_model(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any] | Any
) -> None:
    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)
    monkeypatch.setattr(llm_client, "chat_json", lambda *_args, **_kwargs: payload)


@pytest.fixture(autouse=True)
def _reset_rate_limit() -> None:
    """真实模型限流是进程内状态，每个用例前后清理，避免用例间互相污染。"""
    task_draft_service._REAL_CALL_TIMES.clear()
    yield
    task_draft_service._REAL_CALL_TIMES.clear()


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        admin_id = _ensure_user("v1_draft_admin", "V1 草案管理员")
        student_id = _ensure_user("v1_draft_student", "V1 草案学生")
        other_admin_id = _ensure_user("v1_draft_other_admin", "V1 草案外组织管理员")
        multi_admin_id = _ensure_user("v1_draft_multi_admin", "V1 草案多组织管理员")
        bare_id = _ensure_user("v1_draft_bare", "V1 草案无资料组织管理员")

        org_id = _ensure_org(
            "V1 草案组织", "v1-draft-org", roles={admin_id: "admin", student_id: "member"}
        )
        _ensure_org("V1 草案组织", "v1-draft-org", roles={multi_admin_id: "admin"})
        other_org_id = _ensure_org(
            "V1 草案外组织",
            "v1-draft-other-org",
            roles={other_admin_id: "admin", multi_admin_id: "admin"},
        )
        empty_org_id = _ensure_org(
            "V1 草案无资料组织", "v1-draft-empty-org", roles={bare_id: "admin"}
        )

        admin = _login(client, "v1_draft_admin")
        student = _login(client, "v1_draft_student")
        other_admin = _login(client, "v1_draft_other_admin")
        multi_admin = _login(client, "v1_draft_multi_admin")
        bare = _login(client, "v1_draft_bare")

        activity = _ok(
            client,
            "POST",
            "/api/activities",
            headers=admin,
            body={"title": "秋季招聘会", "org_id": org_id},
            label="创建活动",
        )
        activity_id = int(activity["id"])
        task = _ok(
            client,
            "POST",
            "/api/tasks",
            headers=admin,
            body={"title": "招聘会物资准备", "activity_id": activity_id},
            label="创建任务",
        )

        open_resource_id = _upload_resource(client, admin, org_id, "秋季招聘会策划指南", OPEN_TEXT)
        _open_resource(client, admin, open_resource_id)
        closed_resource_id = _upload_resource(client, admin, org_id, "秋季招聘会内部预算", CLOSED_TEXT)
        foreign_resource_id = _upload_resource(
            client, other_admin, other_org_id, "秋季招聘会外部资料", FOREIGN_TEXT
        )
        _open_resource(client, other_admin, foreign_resource_id)

        yield _Ctx(
            client=client,
            admin=admin,
            student=student,
            other_admin=other_admin,
            multi_admin=multi_admin,
            bare=bare,
            org_id=org_id,
            other_org_id=other_org_id,
            empty_org_id=empty_org_id,
            open_resource_id=open_resource_id,
            closed_resource_id=closed_resource_id,
            foreign_resource_id=foreign_resource_id,
            activity_id=activity_id,
            task_id=int(task["id"]),
        )


# --------------------------------------------------------------------------- #
# mock 结构与来源
# --------------------------------------------------------------------------- #
def test_mock_draft_structure(ctx: _Ctx) -> None:
    data = _draft(
        ctx.client,
        ctx.admin,
        {"prompt": "为秋季招聘会生成任务树", "org_id": ctx.org_id},
        "mock 草案",
    )

    assert set(data) == {"activity_title", "tasks", "sources", "mock"}
    assert data["mock"] is True, "MAAS_MOCK=1 时必须走 mock 分支"
    assert data["activity_title"].strip()
    assert len(data["tasks"]) == 3, "mock 必须返回确定性 3 任务树"

    keys = [item["key"] for item in data["tasks"]]
    assert keys == ["t0", "t1", "t2"], f"任务 key 必须是可发布的稳定 key（实际 {keys}）"
    for item in data["tasks"]:
        assert set(item) == DRAFT_ITEM_KEYS, f"草案字段不符合契约：{set(item) ^ DRAFT_ITEM_KEYS}"
        assert item["title"].strip()
        assert isinstance(item["depends_on_keys"], list)
    assert data["tasks"][1]["depends_on_keys"] == ["t0"], "mock 依赖关系必须自洽"
    assert data["tasks"][2]["depends_on_keys"] == ["t0"]
    _assert_publishable(data["tasks"])


def test_sources_only_include_open_resources(ctx: _Ctx) -> None:
    data = _draft(
        ctx.client,
        ctx.admin,
        {"prompt": "秋季招聘会 物资准备 现场布置 任务树", "org_id": ctx.org_id},
        "来源草案",
    )

    sources = data["sources"]
    assert sources, "命中的开放资料应作为来源返回"
    assert all(set(item) == {"resource_id", "title"} for item in sources)
    resource_ids = {int(item["resource_id"]) for item in sources}
    assert resource_ids == {ctx.open_resource_id}, "只应返回当前用户可用的开放资料"
    assert ctx.closed_resource_id not in resource_ids, "未开放资料不得作为来源"
    assert ctx.foreign_resource_id not in resource_ids, "跨组织资料不得作为来源"
    titles = {item["title"] for item in sources}
    assert titles == {"秋季招聘会策划指南"}


def test_draft_sources_scoped_to_selected_org(ctx: _Ctx) -> None:
    """I2：显式 org_id 只检索该组织；未提供时检索全部可管理组织。"""
    scoped_a = _draft(
        ctx.client,
        ctx.multi_admin,
        {"prompt": "秋季招聘会任务树", "org_id": ctx.org_id},
        "多组织管理员选组织 A",
    )
    assert {item["resource_id"] for item in scoped_a["sources"]} == {ctx.open_resource_id}, (
        "选择组织 A 时不得引用组织 B 的资料"
    )

    scoped_b = _draft(
        ctx.client,
        ctx.multi_admin,
        {"prompt": "秋季招聘会任务树", "org_id": ctx.other_org_id},
        "多组织管理员选组织 B",
    )
    assert {item["resource_id"] for item in scoped_b["sources"]} == {ctx.foreign_resource_id}, (
        "选择组织 B 时不得引用组织 A 的资料"
    )

    unscoped = _draft(
        ctx.client,
        ctx.multi_admin,
        {"prompt": "秋季招聘会任务树"},
        "多组织管理员不选组织",
    )
    assert {item["resource_id"] for item in unscoped["sources"]} == {
        ctx.open_resource_id,
        ctx.foreign_resource_id,
    }, "未提供 org_id 时应检索全部可管理组织的开放资料"

    _err(
        ctx.client,
        "POST",
        "/api/ai/task-draft",
        headers=ctx.admin,
        body={"prompt": "越权选择外组织", "org_id": ctx.other_org_id},
        code=ERR_FORBIDDEN,
        status=403,
        label="单组织管理员选择未管理组织",
    )


def test_requires_manager_org(ctx: _Ctx) -> None:
    """I2：普通成员不可使用草案；可管理但无资料的组织仍可生成。"""
    denied = _err(
        ctx.client,
        "POST",
        "/api/ai/task-draft",
        headers=ctx.student,
        body={"prompt": "学生不选组织"},
        code=ERR_FORBIDDEN,
        status=403,
        label="普通成员使用草案",
    )
    assert "仅组织管理者" in str(denied.get("msg")), "无管理组织时应返回明确提示"

    _err(
        ctx.client,
        "POST",
        "/api/ai/task-draft",
        headers=ctx.student,
        body={"prompt": "学生选择组织", "org_id": ctx.org_id},
        code=ERR_FORBIDDEN,
        status=403,
        label="普通成员选择组织",
    )

    data = _draft(
        ctx.client,
        ctx.bare,
        {"prompt": "无开放资料组织任务树"},
        "无开放资料草案",
    )
    assert data["sources"] == [], "没有开放资料时仍应允许生成"
    assert len(data["tasks"]) == 3


# --------------------------------------------------------------------------- #
# 权限与参数
# --------------------------------------------------------------------------- #
def test_invalid_org_and_param_errors(ctx: _Ctx) -> None:
    _err(
        ctx.client,
        "POST",
        "/api/ai/task-draft",
        headers=ctx.admin,
        body={"prompt": "不存在的组织", "org_id": 99999999},
        code=ERR_NOT_FOUND,
        status=404,
        label="组织不存在",
    )
    _err(
        ctx.client,
        "POST",
        "/api/ai/task-draft",
        headers=ctx.admin,
        body={"prompt": "   "},
        code=ERR_INVALID_PARAM,
        label="空白需求",
    )
    _err(
        ctx.client,
        "POST",
        "/api/ai/task-draft",
        body={"prompt": "未登录草案"},
        code=ERR_UNAUTHORIZED,
        status=401,
        label="未登录草案",
    )


# --------------------------------------------------------------------------- #
# 无副作用
# --------------------------------------------------------------------------- #
def test_draft_does_not_write_business_rows(ctx: _Ctx) -> None:
    before = _row_counts()
    _draft(
        ctx.client,
        ctx.admin,
        {"prompt": "秋季招聘会 物资 排班 任务树", "org_id": ctx.org_id},
        "无写库草案",
    )
    after = _row_counts()
    assert after == before, f"草案接口不得写活动 / 任务 / 资料行（{before} → {after}）"
    assert after[0] >= 1 and after[1] >= 1


# --------------------------------------------------------------------------- #
# 真实模型分支：错误映射、限流与结构校验（monkeypatch，不发起外部调用）
# --------------------------------------------------------------------------- #
def test_invalid_model_output_maps_to_5030(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_args, **_kwargs):
        raise llm_client.LLMError(llm_client.CODE_INVALID_OUTPUT, "LLM 输出不是合法 JSON")

    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)
    monkeypatch.setattr(llm_client, "chat_json", _boom)

    _err(
        ctx.client,
        "POST",
        "/api/ai/task-draft",
        headers=ctx.admin,
        body={"prompt": "真实模型失败草案", "org_id": ctx.org_id},
        code=ERR_INVALID_OUTPUT,
        label="模型输出不合法",
    )


def test_real_branch_rate_limit(ctx: _Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    """I3：真实模型每用户 60 秒 3 次；mock 分支不受限。"""
    _patch_real_model(
        monkeypatch,
        {"activity_title": "限流草案", "tasks": [{"key": "t0", "title": "任务"}]},
    )

    for _ in range(task_draft_service.REAL_RATE_LIMIT):
        data = _draft(
            ctx.client,
            ctx.admin,
            {"prompt": "限流内真实草案", "org_id": ctx.org_id},
            "限流内草案",
        )
        assert data["mock"] is False

    _err(
        ctx.client,
        "POST",
        "/api/ai/task-draft",
        headers=ctx.admin,
        body={"prompt": "超限真实草案", "org_id": ctx.org_id},
        code=ERR_TOO_MANY_REQUESTS,
        status=429,
        label="真实模型超限",
    )

    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: True)
    for _ in range(task_draft_service.REAL_RATE_LIMIT + 2):
        data = _draft(
            ctx.client,
            ctx.admin,
            {"prompt": "mock 不限流", "org_id": ctx.org_id},
            "mock 多次草案",
        )
        assert data["mock"] is True


def test_real_branch_keeps_valid_keys_and_passes_sources(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def _fake_chat_json(system_prompt, user_payload, validate=None):
        captured["system_prompt"] = system_prompt
        captured["user_payload"] = user_payload
        payload = {
            "activity_title": "真实模型草案",
            "tasks": [
                {"key": "prep", "title": "筹备", "depends_on_keys": [], "parent_key": None},
                {
                    "key": "exec",
                    "title": "执行",
                    "sop_guide": "1. 布置场地；2. 现场分工。",
                    "depends_on_keys": ["prep"],
                    "parent_key": None,
                },
            ],
        }
        return validate(payload) if validate is not None else payload

    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)
    monkeypatch.setattr(llm_client, "chat_json", _fake_chat_json)

    data = _draft(
        ctx.client,
        ctx.admin,
        {"prompt": "秋季招聘会 物资准备 任务树", "org_id": ctx.org_id},
        "真实分支草案",
    )

    assert data["mock"] is False
    assert data["activity_title"] == "真实模型草案"
    assert [item["key"] for item in data["tasks"]] == ["prep", "exec"], "合法 key 必须原样保留"
    assert data["tasks"][1]["depends_on_keys"] == ["prep"]
    assert {item["title"] for item in data["sources"]} == {"秋季招聘会策划指南"}
    _assert_publishable(data["tasks"])

    assert captured["system_prompt"] == prompts.render_task_draft_prompt()
    assert "秋季招聘会策划指南" in str(captured["user_payload"]), "检索到的资料必须进入模型输入"
    assert "内部预算" not in str(captured["user_payload"]), "未开放资料不得进入模型输入"


def test_draft_drops_duplicate_keys(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_real_model(
        monkeypatch,
        {
            "activity_title": "重复键草案",
            "tasks": [
                {"key": "a", "title": "任务 A"},
                {"key": "a", "title": "任务 A 重复"},
                {"key": "b", "title": "任务 B", "depends_on_keys": ["a"]},
            ],
        },
    )
    with caplog.at_level(logging.WARNING, logger="app.services.task_draft_service"):
        data = _draft(
            ctx.client,
            ctx.admin,
            {"prompt": "秋季招聘会任务树", "org_id": ctx.org_id},
            "重复 key 草案",
        )

    assert [item["key"] for item in data["tasks"]] == ["a", "b"], "重复 key 的任务必须被丢弃"
    assert data["tasks"][1]["depends_on_keys"] == ["a"], "合法依赖不得被静默重映射"
    _assert_publishable(data["tasks"])
    assert any("重复" in message for message in caplog.messages), "丢弃原因必须记 warning"


def test_draft_drops_dependency_cycle(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_real_model(
        monkeypatch,
        {
            "activity_title": "成环草案",
            "tasks": [
                {"key": "a", "title": "任务 A", "depends_on_keys": ["b"]},
                {"key": "b", "title": "任务 B", "depends_on_keys": ["a"]},
                {"key": "c", "title": "任务 C"},
            ],
        },
    )
    with caplog.at_level(logging.WARNING, logger="app.services.task_draft_service"):
        data = _draft(
            ctx.client,
            ctx.admin,
            {"prompt": "秋季招聘会任务树", "org_id": ctx.org_id},
            "成环草案",
        )

    assert [item["key"] for item in data["tasks"]] == ["c"], "环内任务必须全部丢弃"
    _assert_publishable(data["tasks"])
    assert any("成环" in message for message in caplog.messages)


def test_draft_drops_cross_level_dependency(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_real_model(
        monkeypatch,
        {
            "activity_title": "跨层草案",
            "tasks": [
                {"key": "a", "title": "顶层 A"},
                {"key": "b", "title": "顶层 B"},
                {
                    "key": "child",
                    "title": "子任务",
                    "parent_key": "a",
                    "depends_on_keys": ["b"],
                },
            ],
        },
    )
    with caplog.at_level(logging.WARNING, logger="app.services.task_draft_service"):
        data = _draft(
            ctx.client,
            ctx.admin,
            {"prompt": "秋季招聘会任务树", "org_id": ctx.org_id},
            "跨层依赖草案",
        )

    assert [item["key"] for item in data["tasks"]] == ["a", "b"], "跨层依赖任务必须被丢弃"
    _assert_publishable(data["tasks"])
    assert any("同一层级" in message for message in caplog.messages)


def test_draft_drops_multi_level_parent(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_real_model(
        monkeypatch,
        {
            "activity_title": "多层父草案",
            "tasks": [
                {"key": "a", "title": "顶层 A"},
                {"key": "b", "title": "子任务 B", "parent_key": "a"},
                {"key": "c", "title": "孙任务 C", "parent_key": "b"},
            ],
        },
    )
    with caplog.at_level(logging.WARNING, logger="app.services.task_draft_service"):
        data = _draft(
            ctx.client,
            ctx.admin,
            {"prompt": "秋季招聘会任务树", "org_id": ctx.org_id},
            "多层父草案",
        )

    assert [item["key"] for item in data["tasks"]] == ["a", "b"], "只允许一层父子关系"
    _assert_publishable(data["tasks"])
    assert any("自身还有父任务" in message for message in caplog.messages)


def test_draft_prompt_is_single_source() -> None:
    assert prompts.render_task_draft_prompt() == prompts.TASK_DRAFT_SYSTEM_PROMPT
    assert "只输出一个 JSON 对象" in prompts.TASK_DRAFT_SYSTEM_PROMPT
    assert "不得执行发布" in prompts.TASK_DRAFT_SYSTEM_PROMPT
    assert task_draft_service.MAX_SOURCES <= 3