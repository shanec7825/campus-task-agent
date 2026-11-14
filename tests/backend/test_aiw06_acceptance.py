#!/usr/bin/env python
"""AIW-06 整体验收端到端行为测试（可重复演示的完整协作链路）。

覆盖链路（全部走真实 HTTP 行为）：

1. 组织管理员 / 协作者（活动负责人）/ 成员 ×2 / 外组织成员登录；
2. 协作者发布活动，发布两个同活动任务，第二个依赖第一个；
3. 依赖未完成时报名被拒（4020）；
4. 两名成员报名 → 发布者审批 → 进度 → 提交成果 v1；
5. 规则预审发现时间不一致 → 负责人退回（成员 rejected + 通知）；
6. 成员重提 v2 → 预审通过 → 旧版 v1 验收被拒（4090）→ 最新版验收通过并加分；
7. 第二名成员提交并验收 → 任务全部 verified，依赖解锁后可报名；
8. 催办生成后改期：旧提醒 stale、不计未读，成员收到变更通知；
9. AI 问答写入账本，同一 request_id 重放不重复扣额度；
10. 外组织用户看不到活动 / 任务，不能改期，列表不泄露。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH``、``MAAS_MOCK=1``、``MAAS_API_KEY=''``、
``RUN_SCHEDULER=0``、``AI_DAILY_QUOTA=50``；不触碰 ``backend/campus.db``。
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw06-acceptance-"))

_TEST_DB_PATH = _TMP_DIR / "aiw06.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"
os.environ["AI_DAILY_QUOTA"] = "50"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app import db as app_db  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Notification, OrgMember, Organization, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import reminder_scheduler  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

if Path(app_db.engine.url.database).resolve() != _TEST_DB_PATH.resolve():
    pytest.skip(
        "AIW-06 套件必须单文件运行；"
        f"当前 engine 指向 {app_db.engine.url.database}，避免复用其它套件的临时库",
        allow_module_level=True,
    )


def _cleanup_tmp_dir() -> None:
    """先释放引擎连接池再删库目录；Windows 上未 dispose 会因文件占用删除失败。"""
    try:
        app_db.engine.dispose()
    finally:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)


atexit.register(_cleanup_tmp_dir)

PASSWORD = "TestPass123!"
ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040
ERR_CONFLICT = 4090
ERR_DEPENDENCY = 4020


@dataclass
class _Ctx:
    client: TestClient
    owner: dict[str, str]
    publisher: dict[str, str]
    worker: dict[str, str]
    worker2: dict[str, str]
    outsider: dict[str, str]
    foreign_admin: dict[str, str]
    ids: dict[str, int]
    org_id: int
    foreign_org_id: int


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
        owner_id = _ensure_user("aiw06_owner", "晚会负责人", role="publisher")
        publisher_id = _ensure_user("aiw06_publisher", "团委管理员", role="publisher")
        worker_id = _ensure_user("aiw06_worker", "执行同学", role="student")
        worker2_id = _ensure_user("aiw06_worker2", "执行同学二", role="student")
        outsider_id = _ensure_user("aiw06_outsider", "外院同学", role="student")
        foreign_admin_id = _ensure_user("aiw06_foreign", "外院管理员", role="publisher")

        org_id = _ensure_org(
            "AIW06 晚会组织",
            "aiw06-acceptance",
            roles={
                owner_id: "collaborator",
                publisher_id: "admin",
                worker_id: "member",
                worker2_id: "member",
            },
        )
        foreign_org_id = _ensure_org(
            "AIW06 外院组织",
            "aiw06-foreign",
            roles={outsider_id: "member", foreign_admin_id: "admin"},
        )
        yield _Ctx(
            client=client,
            owner=_login(client, "aiw06_owner"),
            publisher=_login(client, "aiw06_publisher"),
            worker=_login(client, "aiw06_worker"),
            worker2=_login(client, "aiw06_worker2"),
            outsider=_login(client, "aiw06_outsider"),
            foreign_admin=_login(client, "aiw06_foreign"),
            ids={
                "owner": owner_id,
                "publisher": publisher_id,
                "worker": worker_id,
                "worker2": worker2_id,
                "outsider": outsider_id,
                "foreign_admin": foreign_admin_id,
            },
            org_id=org_id,
            foreign_org_id=foreign_org_id,
        )


def _request(client: TestClient, method: str, path: str, *, headers=None, body=None):
    return client.request(method, path, json=body, headers=headers or {})


def _ok(client: TestClient, method: str, path: str, *, headers=None, body=None, label="") -> dict:
    response = _request(client, method, path, headers=headers, body=body)
    try:
        payload = response.json()
    except ValueError:
        raise AssertionError(f"{label}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert response.status_code == 200, (
        f"{label}：期望 HTTP 200，实际 HTTP {response.status_code}"
    )
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


def _create_activity(ctx: _Ctx, title: str, **fields: Any) -> int:
    body: dict[str, Any] = {
        "title": title,
        "org_id": ctx.org_id,
        "description": "中秋晚会整体安排，包含预热宣传与现场布置。",
        "location": "大学生活动中心",
        "start_time": "2026-11-20 19:00",
        "deadline": "2026-11-20 22:00",
    }
    body.update(fields)
    data = _ok(
        ctx.client,
        "POST",
        "/api/activities",
        headers=ctx.owner,
        body=body,
        label=f"创建活动 {title}",
    )
    assert int(data["org_id"]) == ctx.org_id, "活动归属组织与发布请求不一致"
    assert data["location"] == body["location"], "活动地点未按发布请求保存"
    assert str(data["start_time"]).startswith(str(body["start_time"])[:16]), (
        f"活动举办时间未按请求保存：{data['start_time']}"
    )
    return int(data["id"])


def _create_task(ctx: _Ctx, title: str, *, activity_id: int, **fields: Any) -> int:
    body: dict[str, Any] = {
        "title": title,
        "activity_id": activity_id,
        "org_id": ctx.org_id,
        "start_time": "2026-11-20 19:00",
        "deadline": "2026-11-20 22:00",
        "quota": 4,
        "credit_reward": 20,
        "description": "按活动时间与地点完成工作，提交说明与成果链接。",
    }
    body.update(fields)
    data = _ok(
        ctx.client,
        "POST",
        "/api/tasks",
        headers=ctx.publisher,
        body=body,
        label=f"创建任务 {title}",
    )
    assert int(data["activity_id"]) == activity_id, "任务未归属到指定活动"
    assert int(data["org_id"]) == ctx.org_id, "任务组织归属与活动不一致"
    expected_deps = sorted(int(value) for value in (fields.get("depends_on_ids") or []))
    assert sorted(int(value) for value in (data.get("depends_on_ids") or [])) == expected_deps, (
        f"依赖边未按请求保存：{data.get('depends_on_ids')} != {expected_deps}"
    )
    return int(data["id"])


def _apply(ctx: _Ctx, task_id: int, headers, label: str) -> dict:
    data = _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/apply",
        headers=headers,
        label=label,
    )
    return data["application"]


def _decide(ctx: _Ctx, application_id: int, approve: bool, *, reason: str | None = None) -> dict:
    body: dict[str, Any] = {"approve": approve}
    if reason is not None:
        body["reason"] = reason
    return _ok(
        ctx.client,
        "POST",
        f"/api/applications/{application_id}/decide",
        headers=ctx.publisher,
        body=body,
        label=f"审批报名 #{application_id}",
    )


def _task_payload(ctx: _Ctx, task_id: int, headers) -> dict:
    return _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}",
        headers=headers,
        label=f"读取任务 #{task_id}",
    )


def _member_status(payload: dict, user_id: int) -> str | None:
    for member in payload.get("members", []):
        if int(member["user_id"]) == int(user_id):
            return str(member["status"])
    return None


def _submissions(ctx: _Ctx, task_id: int, headers) -> list[dict]:
    return _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/submissions",
        headers=headers,
        label=f"读取任务 #{task_id} 成果版本",
    )["items"]


def _submit(ctx: _Ctx, task_id: int, headers, *, content: str) -> dict:
    return _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submit",
        headers=headers,
        body={"content": content},
        label=f"提交任务 #{task_id}",
    )


def _precheck(ctx: _Ctx, task_id: int, submission_id: int, headers) -> dict:
    return _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/submissions/{submission_id}/precheck",
        headers=headers,
        label=f"预审成果 #{submission_id}",
    )


def _verify(
    ctx: _Ctx,
    task_id: int,
    *,
    pass_: bool,
    user_id: int,
    submission_id: int | None = None,
    reason: str | None = None,
) -> dict:
    body: dict[str, Any] = {"pass": pass_, "user_id": user_id}
    if submission_id is not None:
        body["submission_id"] = submission_id
    if reason is not None:
        body["reason"] = reason
    return _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        headers=ctx.publisher,
        body=body,
        label=f"验收任务 #{task_id} 成员 {user_id}",
    )


def _credits(ctx: _Ctx, headers) -> int:
    return int(
        _ok(ctx.client, "GET", "/api/credits/me", headers=headers, label="读取积分")["credits"]
    )


def _db_notifications(*, task_id: int | None = None, user_id: int | None = None) -> list[Notification]:
    with SessionLocal() as db:
        query = db.query(Notification)
        if task_id is not None:
            query = query.filter(Notification.task_id == int(task_id))
        if user_id is not None:
            query = query.filter(Notification.user_id == int(user_id))
        return list(query.order_by(Notification.id.asc()).all())


def _check_status(result: dict, key: str) -> str:
    return str(next(item for item in result["checks"] if item["key"] == key)["status"])


def test_acceptance_full_collaboration_flow(ctx: _Ctx) -> None:
    """一条完整、可重复执行的晚会协作链路。"""
    activity_id = _create_activity(ctx, "AIW06 中秋晚会")
    resource = _ok(
        ctx.client,
        "POST",
        "/api/resources",
        headers=ctx.owner,
        body={
            "title": "AIW06 预热推文模板",
            "url": "https://example.com/aiw06-promo-template",
            "summary": "往届预热推文的结构参考，时间地点以本届活动为准。",
            "activity_id": activity_id,
        },
        label="创建活动资料",
    )
    assert int(resource["id"]) > 0, "活动资料应真实落库并可追溯到活动"
    task_a = _create_task(
        ctx,
        "AIW06 预热推文",
        activity_id=activity_id,
        quota=3,
        credit_reward=20,
    )
    now = datetime.now().replace(microsecond=0)
    task_b_deadline = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    task_b = _create_task(
        ctx,
        "AIW06 舞台布置",
        activity_id=activity_id,
        deadline=task_b_deadline,
        start_time=task_b_deadline,
        quota=4,
        credit_reward=10,
        depends_on_ids=[task_a],
    )

    # 1. 依赖未完成时不能报名后续任务。
    _err(
        ctx.client,
        "POST",
        f"/api/tasks/{task_b}/apply",
        headers=ctx.worker,
        code=ERR_DEPENDENCY,
        label="依赖未完成时报名舞台布置",
    )

    # 2. 两名成员报名预热推文，发布者审批通过。
    application = _apply(ctx, task_a, ctx.worker, "成员报名预热推文")
    assert application["status"] == "pending"
    decided = _decide(ctx, int(application["id"]), True)
    assert decided["application"]["status"] == "approved"
    assert str(decided["task"]["status"]) == "claimed"

    application2 = _apply(ctx, task_a, ctx.worker2, "成员二报名预热推文")
    decided2 = _decide(ctx, int(application2["id"]), True)
    assert decided2["application"]["status"] == "approved"

    payload = _task_payload(ctx, task_a, ctx.worker)
    assert _member_status(payload, ctx.ids["worker"]) == "not_started"
    assert _member_status(payload, ctx.ids["worker2"]) == "not_started"

    # 3. 成员更新进度并提交 v1（日期与活动要求不一致）。
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_a}/progress",
        headers=ctx.worker,
        body={"content": "已完成预热推文初稿，等待自检。"},
        label="更新进度",
    )
    _submit(
        ctx,
        task_a,
        ctx.worker,
        content="预热推文初稿：9月20日 19:00 大学生活动中心，欢迎参加。",
    )
    versions = _submissions(ctx, task_a, ctx.publisher)
    assert len(versions) == 1 and int(versions[0]["version"]) == 1
    submission_v1 = int(versions[0]["id"])

    precheck_v1 = _precheck(ctx, task_a, submission_v1, ctx.publisher)
    assert precheck_v1["verdict"] == "fail", "错误日期必须被规则预审判定为不通过"
    assert _check_status(precheck_v1, "time_consistency") == "fail"
    assert "9" in next(
        item["evidence"] for item in precheck_v1["checks"] if item["key"] == "time_consistency"
    )

    # 4. 负责人退回：成员状态 rejected，并收到退回通知。
    _verify(ctx, task_a, pass_=False, user_id=ctx.ids["worker"], reason="时间写错，应为 11 月 20 日")
    rejected = _task_payload(ctx, task_a, ctx.worker)
    assert _member_status(rejected, ctx.ids["worker"]) == "rejected"
    rejection_notes = [
        row
        for row in _db_notifications(task_id=task_a, user_id=ctx.ids["worker"])
        if row.title == "验收未通过"
    ]
    assert rejection_notes and "时间写错" in rejection_notes[-1].content

    # 5. 重提 v2；旧版 v1 不能批准新稿。
    _submit(
        ctx,
        task_a,
        ctx.worker,
        content="预热推文定稿：11月20日 19:00 大学生活动中心，欢迎参加。",
    )
    versions = _submissions(ctx, task_a, ctx.publisher)
    assert sorted(int(item["version"]) for item in versions) == [1, 2]
    submission_v2 = int(versions[0]["id"])
    assert int(versions[0]["version"]) == 2, "成果版本列表最新在前"

    precheck_v2 = _precheck(ctx, task_a, submission_v2, ctx.publisher)
    assert precheck_v2["verdict"] == "pass", (
        f"正确日期应通过规则预审，实际 {precheck_v2['verdict']}：{precheck_v2['checks']}"
    )
    assert _check_status(precheck_v2, "time_consistency") == "pass"

    credit_before = _credits(ctx, ctx.worker)
    _err(
        ctx.client,
        "POST",
        f"/api/tasks/{task_a}/verify",
        headers=ctx.publisher,
        body={"pass": True, "user_id": ctx.ids["worker"], "submission_id": submission_v1},
        code=ERR_CONFLICT,
        label="旧版本验收",
    )
    after_old_verify = _task_payload(ctx, task_a, ctx.worker)
    assert _member_status(after_old_verify, ctx.ids["worker"]) == "submitted", (
        "旧版验收被拒后成员状态不应改变"
    )
    assert _credits(ctx, ctx.worker) == credit_before, "旧版验收被拒不得加分"

    _verify(
        ctx,
        task_a,
        pass_=True,
        user_id=ctx.ids["worker"],
        submission_id=submission_v2,
    )
    assert _credits(ctx, ctx.worker) == credit_before + 20, "验收通过后应按 credit_reward 加分"
    verified = _task_payload(ctx, task_a, ctx.worker)
    assert _member_status(verified, ctx.ids["worker"]) == "verified"
    award_notes = [
        row
        for row in _db_notifications(task_id=task_a, user_id=ctx.ids["worker"])
        if row.title == "验收通过，积分到账"
    ]
    assert award_notes, "验收通过应通知成员积分到账"

    # 6. 第二名成员提交并验收，任务全部 verified，依赖解锁。
    _ok(
        ctx.client,
        "POST",
        f"/api/tasks/{task_a}/progress",
        headers=ctx.worker2,
        body={"content": "已完成预热推文初稿。"},
        label="成员二更新进度",
    )
    _submit(
        ctx,
        task_a,
        ctx.worker2,
        content="预热推文定稿：11月20日 19:00 大学生活动中心，欢迎参加。",
    )
    versions2 = _submissions(ctx, task_a, ctx.publisher)
    mine2 = [item for item in versions2 if int(item["user_id"]) == ctx.ids["worker2"]]
    assert mine2 and int(mine2[0]["version"]) == 1, "成员二的首次提交应为 v1"
    submission_worker2 = int(mine2[0]["id"])
    assert _precheck(ctx, task_a, submission_worker2, ctx.publisher)["verdict"] == "pass"
    _verify(ctx, task_a, pass_=True, user_id=ctx.ids["worker2"], submission_id=submission_worker2)
    completed = _task_payload(ctx, task_a, ctx.publisher)
    assert str(completed["status"]) == "verified", (
        f"全部成员验收后任务应为 verified，实际 {completed['status']}"
    )
    assert _member_status(completed, ctx.ids["worker2"]) == "verified", (
        "第二名成员验收后本人状态应为 verified"
    )

    unlocked = _apply(ctx, task_b, ctx.worker2, "依赖解锁后报名舞台布置")
    assert unlocked["status"] == "pending"
    _decide(ctx, int(unlocked["id"]), True)

    # 7. 催办生成后改期：旧提醒失效，成员收到变更通知。
    reminder_scheduler.scan_and_remind(now=now)
    before = _db_notifications(task_id=task_b, user_id=ctx.ids["worker2"])
    reminders = [row for row in before if str(row.dedupe_key or "").startswith("remind:")]
    assert reminders, "改期前应生成催办提醒"
    assert all(int(row.stale) == 0 for row in reminders)

    new_deadline = (now + timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
    changed = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_b}",
        headers=ctx.publisher,
        body={"deadline": new_deadline},
        label="改期舞台布置",
    )
    change = changed.get("change") or {}
    assert change.get("kind") == "deadline"
    # task_b 当前只有 worker2 一条 remind: 提醒；若后续新增多级提醒需同步调整。
    assert int(change.get("reminders_stale", 0)) == 1
    after = _db_notifications(task_id=task_b, user_id=ctx.ids["worker2"])
    old_reminders = [row for row in after if str(row.dedupe_key or "").startswith("remind:")]
    assert old_reminders and all(int(row.stale) == 1 for row in old_reminders)
    change_notes = [row for row in after if str(row.dedupe_key or "").startswith("change:deadline:")]
    assert change_notes and new_deadline in change_notes[-1].content

    listed = _ok(
        ctx.client,
        "GET",
        "/api/notifications?limit=200",
        headers=ctx.worker2,
        label="通知列表",
    )
    stale_items = [item for item in listed["items"] if int(item.get("stale") or 0) == 1]
    assert stale_items, "通知列表仍返回失效提醒供追溯"
    assert listed["unread"] == len(
        [
            item
            for item in listed["items"]
            if int(item.get("is_read") or 0) == 0 and int(item.get("stale") or 0) == 0
        ]
    ), "未读计数不能包含失效提醒"

    # 8. AI 问答：权限内回答 + 引用范围 + 额度账本 + request_id 幂等。
    foreign_task = int(
        _ok(
            ctx.client,
            "POST",
            "/api/tasks",
            headers=ctx.foreign_admin,
            body={
                "title": "AIW06 外院独立任务",
                "org_id": ctx.foreign_org_id,
                "description": "外院组织任务，不应出现在本院成员的 AI 回答与引用中。",
                "deadline": new_deadline,
            },
            label="创建外组织独立任务",
        )["id"]
    )
    usage_before = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="读取用量")
    chat = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.worker,
        body={"message": "预热推文任务的要求是什么？", "request_id": "aiw06-e2e-chat-1"},
        label="AI 问答",
    )
    assert chat["mock"] is True
    assert chat["assistant_message"]["content"].strip(), "AI 回答不能为空"
    citations = chat["assistant_message"]["citations"]
    assert citations, "权限内回答应包含来源"
    assert all(item["type"] == "task" for item in citations), "当前引用类型应为任务"
    cited_ids = {int(item["id"]) for item in citations}
    assert cited_ids <= {task_a, task_b}, f"引用不应包含范围外任务：{cited_ids}"
    assert foreign_task not in cited_ids, "外组织任务不得进入引用"
    assert "外院独立任务" not in chat["assistant_message"]["content"], "外组织任务不得进入回答正文"
    usage_after = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="读取用量")
    assert usage_after["used"] == usage_before["used"] + 1

    replay = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.worker,
        body={"message": "预热推文任务的要求是什么？", "request_id": "aiw06-e2e-chat-1"},
        label="AI 问答重放",
    )
    assert replay["replayed"] is True, "同一 request_id 重放应返回首次结果"
    usage_replay = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="读取用量")
    assert usage_replay["used"] == usage_after["used"], "重放不得重复扣额度"

    # 9. 跨组织隔离：不可见资源统一按不存在处理，列表不泄露。
    _err(
        ctx.client,
        "GET",
        f"/api/activities/{activity_id}",
        headers=ctx.outsider,
        code=ERR_NOT_FOUND,
        status=404,
        label="外组织读取活动",
    )
    _err(
        ctx.client,
        "GET",
        f"/api/tasks/{task_a}",
        headers=ctx.outsider,
        code=ERR_NOT_FOUND,
        status=404,
        label="外组织读取任务",
    )
    _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_a}",
        headers=ctx.foreign_admin,
        body={"deadline": new_deadline},
        code=ERR_NOT_FOUND,
        status=404,
        label="外组织管理员改期",
    )
    listing = _ok(ctx.client, "GET", "/api/tasks", headers=ctx.outsider, label="外组织任务列表")
    listed_ids = {int(item["id"]) for item in listing["items"]}
    assert task_a not in listed_ids and task_b not in listed_ids