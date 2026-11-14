#!/usr/bin/env python
"""V1 整批发布后端行为测试（契约 `C-BATCH-PUBLISH@1`）。

覆盖范围（全部通过真实 HTTP 行为验证）：

1. 只填活动、``tasks=[]``：成功创建活动，任务计数不变；
2. 活动 + 2 任务（含依赖与一层子任务）+ 1 个自动 key 任务：响应顺序与请求一致，
   ``ActivityOut`` / ``TaskOut`` 字段、``parent_id`` / ``depends_on`` / ``depends_on_ids``、
   边表与活动详情任务树一致；
3. 依赖成环 ``4001``、未知依赖 / 父任务 key ``4001``、跨层级依赖 ``4001``；
4. 非组织 admin/collaborator 调用 ``4030``；
5. 任一失败后活动 / 任务 / 依赖行数均不变（整体回滚）。

隔离性：在导入 ``app`` 之前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立
SQLite 文件，关闭调度器并强制 ``MAAS_MOCK=1``；不触碰 ``backend/campus.db``。

认证：fixture 直接写库准备 ``teacher01``（组织 ``admin``）与 ``student01``（组织
``member``），再登录取 Cookie + CSRF 请求头；不依赖共享 client 的 cookie jar。

可独立运行：``pytest tests/backend/test_v1_batch_publish.py``。
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

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-batch-publish-"))
_TEST_DB_PATH = _TMP_DIR / "batch_publish.db"

# 必须在导入 app 之前完成：app.db 在模块导入时按 DATABASE_PATH 创建引擎。
os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Activity,
    KbEntry,
    OrgMember,
    Organization,
    Task,
    TaskDependency,
    User,
)
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040

#: 测试账号的固定密码；fixture 直接写 ``password_hash`` 与 ``status='active'``。
PASSWORD = "TestPass123!"


@dataclass
class _Ctx:
    client: TestClient
    teacher: dict[str, str]
    student: dict[str, str]
    teacher_id: int
    org_id: int


# --------------------------------------------------------------------------- #
# HTTP 工具（Cookie 会话 + 双提交 CSRF）
# --------------------------------------------------------------------------- #
def _payload(
    client: TestClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str],
    body: Any = None,
    label: str = "",
) -> dict:
    response = client.request(method, path, json=body, headers=headers)
    try:
        payload = response.json()
    except ValueError:
        raise AssertionError(f"{label}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert isinstance(payload, dict), f"{label}：响应体不是对象（HTTP {response.status_code}）"
    return payload


def _ok(client, method, path, *, headers, body=None, label="") -> dict:
    payload = _payload(client, method, path, headers=headers, body=body, label=label)
    assert payload.get("code") == 0, (
        f"{label}：期望 code=0，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    data = payload.get("data")
    assert isinstance(data, dict), f"{label}：data 不是对象（{type(data).__name__}）"
    return data


def _err(client, method, path, *, code, headers, body=None, label="", status=200) -> dict:
    response = client.request(method, path, json=body, headers=headers)
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
        f"登录 {username}：HTTP {response.status_code}，code={payload.get('code')}（{payload.get('msg')}）"
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


def _ensure_org(name: str, slug: str, *, admin_id: int, member_ids: tuple[int, ...] = ()) -> int:
    with SessionLocal() as db:
        org = db.query(Organization).filter(Organization.slug == slug).first()
        if org is None:
            org = Organization(name=name, slug=slug, status="active")
            db.add(org)
            db.flush()
        for user_id, role in ((admin_id, "admin"), *((mid, "member") for mid in member_ids)):
            row = (
                db.query(OrgMember)
                .filter(OrgMember.org_id == int(org.id), OrgMember.user_id == int(user_id))
                .first()
            )
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
        db.commit()
        db.refresh(org)
        return int(org.id)


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        teacher_id = _ensure_user("teacher01", "王老师", role="publisher")
        student_id = _ensure_user("student01", "李同学", role="student")
        org_id = _ensure_org(
            "V1 整批发布测试组织",
            "v1-batch-publish",
            admin_id=teacher_id,
            member_ids=(student_id,),
        )
        teacher = _login(client, "teacher01")
        student = _login(client, "student01")
        yield _Ctx(
            client=client,
            teacher=teacher,
            student=student,
            teacher_id=teacher_id,
            org_id=org_id,
        )


# --------------------------------------------------------------------------- #
# 业务辅助
# --------------------------------------------------------------------------- #
def _counts() -> tuple[int, int, int]:
    """当前库的活动 / 任务 / 依赖边行数。"""
    with SessionLocal() as db:
        return (
            int(db.query(Activity).count()),
            int(db.query(Task).count()),
            int(db.query(TaskDependency).count()),
        )


def _batch_body(
    ctx: _Ctx, tasks: list[dict], *, title: str = "迎新晚会", org_id: int | None = None
) -> dict:
    return {
        "activity": {
            "title": title,
            "start_time": "2026-12-01T18:00",
            "deadline": "2026-12-01T22:00",
            "org_id": ctx.org_id if org_id is None else org_id,
        },
        "tasks": tasks,
    }


def _batch(ctx: _Ctx, tasks: list[dict], *, headers: dict[str, str] | None = None, title: str = "迎新晚会") -> dict:
    return _payload(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        headers=headers or ctx.teacher,
        body=_batch_body(ctx, tasks, title=title),
        label="整批发布",
    )


# --------------------------------------------------------------------------- #
# 用例
# --------------------------------------------------------------------------- #
def test_publish_batch_without_tasks(ctx: _Ctx) -> None:
    """只填活动、``tasks=[]``：成功创建活动，任务与依赖计数不变。"""
    before = _counts()
    data = _ok(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        headers=ctx.teacher,
        body=_batch_body(ctx, [], title="  零任务活动  "),
        label="零任务整批发布",
    )

    assert data.get("tasks") == [], f"零任务批次应返回空 tasks，实际 {data.get('tasks')!r}"
    activity = data.get("activity")
    assert isinstance(activity, dict), "响应缺少 activity 对象"
    assert activity.get("title") == "零任务活动", "活动标题应去除首尾空白"
    assert activity.get("owner_id") == ctx.teacher_id
    assert activity.get("org_id") == ctx.org_id
    assert activity.get("status") == "published"

    detail = _ok(
        ctx.client,
        "GET",
        f"/api/activities/{activity['id']}",
        headers=ctx.teacher,
        label="零任务活动详情",
    )
    assert detail.get("tasks") == [], "零任务活动详情任务树应为空"
    assert (detail.get("progress") or {}).get("total_tasks") == 0

    after = _counts()
    assert after[0] == before[0] + 1, "应只新增 1 个活动"
    assert after[1] == before[1], "零任务批次不应新增任务"
    assert after[2] == before[2], "零任务批次不应新增依赖边"


def test_publish_batch_with_dependencies_and_subtask(ctx: _Ctx) -> None:
    """多任务（依赖 + 一层子任务 + 自动 key）一次性创建，顺序与引用关系正确。"""
    before = _counts()
    drafts = [
        {"key": "plan", "title": "总策划", "quota": 2, "credit_reward": 20},
        {"key": "poster", "title": "宣传海报", "depends_on_keys": ["plan"]},
        {"key": "poster_design", "title": "海报设计", "parent_key": "poster"},
        {"title": "物料采购"},
    ]
    data = _ok(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        headers=ctx.teacher,
        body=_batch_body(ctx, drafts),
        label="带依赖与子任务的整批发布",
    )

    activity = data["activity"]
    tasks = data["tasks"]
    assert isinstance(tasks, list) and len(tasks) == 4, f"应返回 4 个任务，实际 {len(tasks)}"
    assert [task["title"] for task in tasks] == ["总策划", "宣传海报", "海报设计", "物料采购"], (
        "响应任务顺序应与请求一致"
    )
    assert len({task["id"] for task in tasks}) == 4, "任务 id 应互不相同"
    for task in tasks:
        assert task["activity_id"] == activity["id"], "任务应归属本批次活动"
        assert task["org_id"] == ctx.org_id, "任务应继承活动组织"
        assert task["publisher_id"] == ctx.teacher_id
        assert task["status"] == "published"

    plan, poster, design, purchase = tasks
    assert poster["depends_on_ids"] == [plan["id"]], "依赖应落到边表派生字段"
    assert poster["depends_on"] == plan["id"], "旧 depends_on 应同步为第一个前置"
    assert design["parent_id"] == poster["id"], "子任务 parent_id 应指向批内父任务"
    assert purchase["parent_id"] is None

    after = _counts()
    assert after[0] == before[0] + 1
    assert after[1] == before[1] + 4
    assert after[2] == before[2] + 1, "应只新增 1 条依赖边"

    detail = _ok(
        ctx.client,
        "GET",
        f"/api/activities/{activity['id']}",
        headers=ctx.teacher,
        label="活动详情任务树",
    )
    tree = detail.get("tasks")
    assert isinstance(tree, list), "活动详情缺少任务树"
    assert [node["title"] for node in tree] == ["总策划", "宣传海报", "物料采购"], (
        "活动详情第一层任务应按创建顺序，且不含子任务"
    )
    poster_node = next(node for node in tree if node["title"] == "宣传海报")
    assert [child["title"] for child in poster_node["children"]] == ["海报设计"]

    listed = _ok(
        ctx.client,
        "GET",
        f"/api/tasks?activity_id={activity['id']}&include_sub=true",
        headers=ctx.teacher,
        label="活动任务列表",
    )
    assert {item["id"] for item in listed["items"]} == {task["id"] for task in tasks}


def test_publish_batch_dependency_cycle_rolls_back(ctx: _Ctx) -> None:
    """批内依赖成环：``4001`` 且活动 / 任务 / 依赖行数不变。"""
    before = _counts()
    payload = _err(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body=_batch_body(
            ctx,
            [
                {"key": "a", "title": "A", "depends_on_keys": ["b"]},
                {"key": "b", "title": "B", "depends_on_keys": ["a"]},
            ],
            title="成环批次",
        ),
        label="依赖成环",
    )
    assert "环" in str(payload.get("msg")), f"错误消息应指出成环，实际 {payload.get('msg')!r}"
    assert _counts() == before, "成环失败后不得留下任何活动 / 任务 / 依赖行"


def test_publish_batch_unknown_key_rolls_back(ctx: _Ctx) -> None:
    """依赖或父任务引用批外 key：``4001``，消息包含该 key，且不写库。"""
    before = _counts()
    payload = _err(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body=_batch_body(
            ctx,
            [{"key": "plan", "title": "总策划", "depends_on_keys": ["ghost"]}],
            title="未知依赖",
        ),
        label="未知依赖 key",
    )
    assert "ghost" in str(payload.get("msg")), "错误消息应明确指出未知 key"

    payload = _err(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body=_batch_body(
            ctx,
            [{"key": "plan", "title": "总策划", "parent_key": "ghost"}],
            title="未知父任务",
        ),
        label="未知父任务 key",
    )
    assert "ghost" in str(payload.get("msg")), "错误消息应明确指出未知父任务 key"
    assert _counts() == before, "未知 key 失败后不得留下任何行"


def test_publish_batch_cross_level_dependency_rolls_back(ctx: _Ctx) -> None:
    """顶层任务依赖子任务（跨层级）：``4001`` 且不写库。"""
    before = _counts()
    payload = _err(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body=_batch_body(
            ctx,
            [
                {"key": "parent", "title": "父任务"},
                {"key": "child", "title": "子任务", "parent_key": "parent"},
                {"key": "top", "title": "独立任务", "depends_on_keys": ["child"]},
            ],
            title="跨层级依赖",
        ),
        label="跨层级依赖",
    )
    assert "层级" in str(payload.get("msg")), f"错误消息应指出层级，实际 {payload.get('msg')!r}"
    assert _counts() == before, "跨层级失败后不得留下任何行"


def test_publish_batch_requires_org_publish_role(ctx: _Ctx) -> None:
    """组织 member 无发布权：``4030``，且不写库；``POST /api/activities`` 行为不变。"""
    before = _counts()
    payload = _err(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        code=ERR_FORBIDDEN,
        headers=ctx.student,
        body=_batch_body(ctx, [{"key": "plan", "title": "总策划"}], title="无权限批次"),
        label="无组织权限",
        status=403,
    )
    assert payload.get("data") is None
    assert _counts() == before, "无权限失败后不得写库"

    # 既有单活动创建接口保持原行为：同样按组织发布权判定。
    _err(
        ctx.client,
        "POST",
        "/api/activities",
        code=ERR_FORBIDDEN,
        headers=ctx.student,
        body={"title": "单活动", "org_id": ctx.org_id},
        label="成员创建单活动",
        status=403,
    )
    assert _counts() == before

def test_publish_batch_indexes_tasks_into_kb(ctx: _Ctx) -> None:
    """I1：commit 后批量任务逐个安全入库，全部任务都能被知识库命中。"""
    data = _ok(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        headers=ctx.teacher,
        body=_batch_body(
            ctx,
            [
                {"key": "plan", "title": "总策划", "description": "统筹整场晚会"},
                {"key": "poster", "title": "宣传海报", "depends_on_keys": ["plan"]},
                {"key": "design", "title": "海报设计", "parent_key": "poster"},
            ],
            title="知识库入库批次",
        ),
        label="知识库入库批次",
    )
    task_ids = [int(task["id"]) for task in data["tasks"]]
    with SessionLocal() as db:
        indexed = {
            int(row.task_id)
            for row in db.query(KbEntry).filter(KbEntry.task_id.in_(task_ids)).all()
        }
    assert indexed == set(task_ids), (
        f"批量任务应全部写入知识库，期望 {sorted(set(task_ids))}，实际 {sorted(indexed)}"
    )


def test_publish_batch_rolls_back_after_flush(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I2：写库并 flush 后依赖写入失败，``rollback`` 使活动 / 任务 / 依赖计数还原。"""
    before = _counts()
    from app.services import activity_service as activity_service

    seen: dict[str, int] = {}

    def _boom(db: Session, task: Task, depends_on_ids: list[int]) -> None:
        seen["task_id"] = int(task.id)
        seen["tasks_in_tx"] = int(db.query(Task).count())
        raise RuntimeError("flush 后失败")

    # 必须打在服务层实际引用的符号上，pytest 会在用例结束后自动还原。
    monkeypatch.setattr(activity_service.task_graph_service, "replace_dependencies", _boom)

    with pytest.raises(RuntimeError, match="flush 后失败"):
        ctx.client.post(
            "/api/activities/publish-batch",
            json=_batch_body(
                ctx,
                [
                    {"key": "plan", "title": "总策划"},
                    {"key": "poster", "title": "宣传海报", "depends_on_keys": ["plan"]},
                ],
                title="flush 后失败批次",
            ),
            headers=ctx.teacher,
        )

    assert seen.get("task_id"), "失败应发生在任务 flush 拿到 id 之后"
    assert seen.get("tasks_in_tx", 0) >= 2, "失败前活动下的任务应已写入当前事务"
    assert _counts() == before, "写入后失败也必须整体回滚"


@pytest.mark.parametrize(
    ("label", "tasks", "code", "status", "keyword", "missing_org"),
    [
        (
            "重复 key",
            [{"key": "dup", "title": "A"}, {"key": "dup", "title": "B"}],
            ERR_INVALID_PARAM,
            200,
            "重复",
            False,
        ),
        (
            "父任务自指",
            [{"key": "plan", "title": "总策划", "parent_key": "plan"}],
            ERR_INVALID_PARAM,
            200,
            "自己",
            False,
        ),
        (
            "三层父任务",
            [
                {"key": "a", "title": "A"},
                {"key": "b", "title": "B", "parent_key": "a"},
                {"key": "c", "title": "C", "parent_key": "b"},
            ],
            ERR_INVALID_PARAM,
            200,
            "不可继续拆分",
            False,
        ),
        (
            "组织不存在",
            [{"key": "plan", "title": "总策划"}],
            ERR_NOT_FOUND,
            404,
            "组织不存在",
            True,
        ),
    ],
)
def test_publish_batch_boundary_errors(
    ctx: _Ctx,
    label: str,
    tasks: list[dict],
    code: int,
    status: int,
    keyword: str,
    missing_org: bool,
) -> None:
    """重复 key / 父任务自指 / 三层父任务 / 组织不存在：返回对应错误码且不写库。"""
    before = _counts()
    org_id = ctx.org_id + 999_999 if missing_org else None
    payload = _err(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        code=code,
        headers=ctx.teacher,
        body=_batch_body(ctx, tasks, title=label, org_id=org_id),
        label=label,
        status=status,
    )
    assert keyword in str(payload.get("msg")), (
        f"{label}：错误消息应包含 {keyword!r}，实际 {payload.get('msg')!r}"
    )
    assert _counts() == before, f"{label}：失败后不得留下任何活动 / 任务 / 依赖行"

def test_publish_batch_invalid_acceptance_rolls_back(ctx: _Ctx) -> None:
    """批内任务 ``extras.acceptance`` 非法：``4001`` 且不写活动 / 任务 / 依赖行。"""
    before = _counts()
    payload = _err(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        code=ERR_INVALID_PARAM,
        headers=ctx.teacher,
        body=_batch_body(
            ctx,
            [
                {"key": "ok", "title": "合法任务"},
                {
                    "key": "bad",
                    "title": "非法策略任务",
                    "extras": {"acceptance": {"modes": ["video"]}},
                },
            ],
            title="非法提交策略",
        ),
        label="非法 acceptance",
    )
    assert "成果提交方式配置不合法" in str(payload.get("msg")), (
        f"错误消息应指出提交方式非法，实际 {payload.get('msg')!r}"
    )
    assert _counts() == before, "非法策略失败后不得留下任何活动 / 任务 / 依赖行"


def test_publish_batch_normalizes_acceptance(ctx: _Ctx) -> None:
    """合法 acceptance 经 normalize_acceptance 规范化后写入任务，其它 extras 键保留。"""
    data = _ok(
        ctx.client,
        "POST",
        "/api/activities/publish-batch",
        headers=ctx.teacher,
        body=_batch_body(
            ctx,
            [
                {
                    "key": "file",
                    "title": "文件成果任务",
                    "extras": {
                        "custom": "keep",
                        "acceptance": {
                            "modes": ["file", "file"],
                            "allowed_exts": [".PDF"],
                            "ai_precheck": True,
                        },
                    },
                }
            ],
            title="规范化提交策略",
        ),
        label="规范化 acceptance",
    )
    task_id = int(data["tasks"][0]["id"])
    detail = _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}",
        headers=ctx.teacher,
        label="任务详情",
    )
    extras = detail["extras"]
    assert extras["custom"] == "keep", "其它 extras 键应原样保留"
    assert extras["acceptance"] == {
        "modes": ["file"],
        "allowed_exts": [".pdf"],
        "ai_precheck": True,
    }, "acceptance 策略应去重并规范化扩展名大小写"