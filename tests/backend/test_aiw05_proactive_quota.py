#!/usr/bin/env python
"""AIW-05 主动协作与额度后端行为测试（契约 `C-REMINDER-STALE@1` / `C-TASK-CHANGE@1` /
`C-TASK-CHANGE-API@1` / `C-AI-USAGE@1`）。

覆盖范围（全部走真实 HTTP 行为与真实调度函数）：

1. 催办生成后改期：旧提醒 stale、未读计数排除、变更通知含旧值/新值/后续任务；
2. 按新截止时间扫描生成新提醒，旧通知保留；
3. 取消任务：旧提醒全部 stale、变更通知、调度器不再生成提醒；
4. 改期影响预览的成员/后续任务、下游可见性过滤与权限矩阵；
5. 相同改期、等价格式、空串清除与非法截止时间的行为；
6. 逾期 `overdue:` / `overdue_pub:` 提醒失效与失效项不可标记已读；
7. 问答写账本、usage 统计、重复 request_id 重放且不重复计费；
8. 额度为 0 时问答 4290，通知与任务接口及 PATCH 写操作仍可用；
9. 模型调用期间已提交超限时的二次额度检查；
10. 真实模型成功路径写 settled 账本；
11. 模型失败不扣额度；
12. 跨账号用量隔离。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH``、``MAAS_MOCK=1``、``MAAS_API_KEY=''``、
``RUN_SCHEDULER=0``、``AI_DAILY_QUOTA=50``；不触碰 ``backend/campus.db``。
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw05-proactive-quota-"))
_TEST_DB_PATH = _TMP_DIR / "aiw05.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"
os.environ["AI_DAILY_QUOTA"] = "50"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.agents import llm_client  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AiMessage,
    AiUsageLedger,
    Notification,
    Task,
    TaskApplication,
    TaskDependency,
    TaskMember,
    User,
)
from app.security import hash_password  # noqa: E402
from app.services import ai_service, reminder_scheduler  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

PASSWORD = "TestPass123!"
ERR_FORBIDDEN = 4030
ERR_NOT_FOUND = 4040
ERR_QUOTA = 4290


@dataclass
class _Ctx:
    client: TestClient
    publisher: dict[str, str]
    worker: dict[str, str]
    outsider: dict[str, str]
    publisher_id: int
    worker_id: int
    outsider_id: int


def _request(client: TestClient, method: str, path: str, *, headers=None, body=None):
    return client.request(method, path, json=body, headers=headers or {})


def _payload(client: TestClient, method: str, path: str, *, headers=None, body=None, label=""):
    response = _request(client, method, path, headers=headers, body=body)
    try:
        payload = response.json()
    except ValueError:
        raise AssertionError(f"{label}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert isinstance(payload, dict), f"{label}：响应体不是对象（HTTP {response.status_code}）"
    return response, payload


def _ok(client: TestClient, method: str, path: str, *, headers=None, body=None, label="") -> dict:
    _, payload = _payload(client, method, path, headers=headers, body=body, label=label)
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
    status: int | None = None,
) -> dict:
    response, payload = _payload(client, method, path, headers=headers, body=body, label=label)
    assert payload.get("code") == code, (
        f"{label}：期望 code={code}，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    if status is not None:
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


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        publisher_id = _ensure_user("aiw05_publisher", "协作发布者", role="publisher")
        worker_id = _ensure_user("aiw05_worker", "协作执行者", role="student")
        outsider_id = _ensure_user("aiw05_outsider", "协作路人", role="student")
        yield _Ctx(
            client=client,
            publisher=_login(client, "aiw05_publisher"),
            worker=_login(client, "aiw05_worker"),
            outsider=_login(client, "aiw05_outsider"),
            publisher_id=publisher_id,
            worker_id=worker_id,
            outsider_id=outsider_id,
        )


def _create_task(
    ctx: _Ctx,
    title: str,
    *,
    deadline: str | None,
    member_status: str = "in_progress",
) -> int:
    with SessionLocal() as db:
        task = Task(
            title=title,
            publisher_id=ctx.publisher_id,
            status="published",
            claim_type="open",
            deadline=deadline,
            extras={},
            credit_reward=0,
        )
        db.add(task)
        db.flush()
        task_id = int(task.id)
        db.add(
            TaskApplication(
                task_id=task_id,
                user_id=ctx.worker_id,
                status="approved",
                decided_by=ctx.publisher_id,
            )
        )
        db.add(
            TaskMember(
                task_id=task_id,
                user_id=ctx.worker_id,
                status=member_status,
            )
        )
        db.commit()
        return task_id


def _add_downstream(
    ctx: _Ctx, upstream_id: int, title: str, publisher_id: int | None = None
) -> int:
    with SessionLocal() as db:
        downstream = Task(
            title=title,
            publisher_id=ctx.publisher_id if publisher_id is None else publisher_id,
            status="published",
            claim_type="open",
            extras={},
            credit_reward=0,
        )
        db.add(downstream)
        db.flush()
        db.add(TaskDependency(task_id=int(downstream.id), depends_on_id=int(upstream_id)))
        db.commit()
        return int(downstream.id)


def _notifications(task_id: int, user_id: int) -> list[Notification]:
    with SessionLocal() as db:
        return list(
            db.query(Notification)
            .filter(Notification.task_id == task_id, Notification.user_id == user_id)
            .order_by(Notification.id.asc())
            .all()
        )


def _all_notifications(user_id: int) -> list[Notification]:
    with SessionLocal() as db:
        return list(
            db.query(Notification)
            .filter(Notification.user_id == user_id)
            .order_by(Notification.id.asc())
            .all()
        )


def test_reschedule_stales_old_reminder_and_notifies(ctx: _Ctx) -> None:
    now = datetime.now().replace(microsecond=0)
    task_id = _create_task(ctx, "AIW05 改期任务", deadline=(now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))

    created = reminder_scheduler.scan_and_remind(now=now)
    assert created >= 1, "改期前应至少生成一条催办"
    before = _notifications(task_id, ctx.worker_id)
    reminders = [row for row in before if (row.dedupe_key or "").startswith("remind:")]
    assert reminders, "应存在 remind: 前缀的催办通知"
    assert all(row.stale == 0 for row in reminders), "改期前提醒不应失效"

    new_deadline = (now + timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")
    data = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"deadline": new_deadline},
        label="改期",
    )
    change = data.get("change") or {}
    assert change.get("kind") == "deadline"
    assert change.get("old_deadline") != change.get("new_deadline")
    assert change.get("reminders_stale", 0) >= 1

    after = _notifications(task_id, ctx.worker_id)
    old_reminders = [row for row in after if (row.dedupe_key or "").startswith("remind:")]
    assert old_reminders
    assert all(row.stale == 1 for row in old_reminders), "改期后旧提醒必须失效"

    change_rows = [row for row in after if (row.dedupe_key or "").startswith("change:deadline:")]
    assert change_rows, "改期应生成变更通知"
    content = change_rows[0].content
    assert "截止时间由" in content and "调整为" in content
    assert new_deadline in content

    # 未读计数排除失效提醒；列表仍返回失效提醒供追溯。
    listed = _ok(ctx.client, "GET", "/api/notifications?limit=200", headers=ctx.worker, label="通知列表")
    items = listed["items"]
    stale_items = [item for item in items if item.get("task_id") == task_id and item.get("stale") == 1]
    assert stale_items, "通知列表应返回 stale 标记"
    assert listed["unread"] == len([item for item in items if item.get("is_read") == 0 and item.get("stale") == 0])

    # 按新时间扫描生成新提醒，旧提醒保留。
    reminder_scheduler.scan_and_remind(now=now)
    latest = _notifications(task_id, ctx.worker_id)
    active = [row for row in latest if (row.dedupe_key or "").startswith("remind:") and row.stale == 0]
    assert active, "按新截止时间应生成有效提醒"
    assert active[-1].dedupe_key != old_reminders[-1].dedupe_key
    assert any(row.stale == 1 for row in latest), "旧提醒应保留并保持失效"


def test_cancel_stales_all_reminders_and_stops_scan(ctx: _Ctx) -> None:
    now = datetime.now().replace(microsecond=0)
    task_id = _create_task(ctx, "AIW05 取消任务", deadline=(now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))
    reminder_scheduler.scan_and_remind(now=now)
    before = _notifications(task_id, ctx.worker_id)
    assert before and all(row.stale == 0 for row in before)

    data = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"status": "cancelled"},
        label="取消任务",
    )
    assert (data.get("change") or {}).get("kind") == "cancelled"
    after = _notifications(task_id, ctx.worker_id)
    assert any((row.dedupe_key or "").startswith("change:cancelled:") for row in after)
    assert all(row.stale == 1 for row in after if (row.dedupe_key or "").startswith(("remind:", "overdue:", "unassigned:")))
    stale_id = next(int(row.id) for row in after if row.stale == 1)
    read_result = _ok(
        ctx.client,
        "POST",
        "/api/notifications/read",
        headers=ctx.worker,
        body={"ids": [stale_id]},
        label="失效提醒标记已读",
    )
    assert read_result["updated"] == 0, "失效提醒不计入已读更新"

    count_before = len(_all_notifications(ctx.worker_id))
    reminder_scheduler.scan_and_remind(now=now)
    assert len(_all_notifications(ctx.worker_id)) == count_before, "取消后调度器不应再生成提醒"


def test_change_impact_preview_and_permissions(ctx: _Ctx) -> None:
    now = datetime.now().replace(microsecond=0)
    task_id = _create_task(ctx, "AIW05 影响预览", deadline=(now + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"))
    downstream_id = _add_downstream(ctx, task_id, "AIW05 后续任务")

    impact = _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/change-impact?deadline={(now + timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')}",
        headers=ctx.publisher,
        label="影响预览",
    )
    assert impact["task_id"] == task_id
    assert impact["reminders_reset"] is True
    assert [member["id"] for member in impact["affected_members"]] == [ctx.worker_id]
    assert [task["id"] for task in impact["downstream_tasks"]] == [downstream_id]
    assert ctx.publisher_id in impact["notified_user_ids"]
    assert ctx.worker_id in impact["notified_user_ids"]

    _err(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/change-impact",
        code=ERR_FORBIDDEN,
        headers=ctx.worker,
        label="成员不能预览改期",
        status=403,
    )
    _err(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/change-impact",
        code=ERR_NOT_FOUND,
        headers=ctx.outsider,
        label="无关用户不可见",
        status=404,
    )
    _err(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/change-impact?deadline=not-a-date",
        code=4001,
        headers=ctx.publisher,
        label="非法截止时间",
    )


def test_impact_hides_invisible_downstream_and_rejects_invalid_deadline(ctx: _Ctx) -> None:
    now = datetime.now().replace(microsecond=0)
    task_id = _create_task(ctx, "AIW05 越权下游", deadline=(now + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"))
    hidden_id = _add_downstream(ctx, task_id, "他人发布的后续任务", publisher_id=ctx.outsider_id)

    impact = _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/change-impact?deadline={(now + timedelta(days=4)).strftime('%Y-%m-%d %H:%M:%S')}",
        headers=ctx.publisher,
        label="过滤不可见下游",
    )
    assert all(task["id"] != hidden_id for task in impact["downstream_tasks"]), "不得返回无权查看的下游任务"
    for task in impact["downstream_tasks"]:
        assert set(task.keys()) == {"id", "title", "status"}, "下游任务只暴露契约字段"

    changed = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"deadline": (now + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")},
        label="改期返回下游",
    )
    change = changed.get("change") or {}
    assert all(task["id"] != hidden_id for task in change.get("downstream_tasks", [])), (
        "PATCH 响应也不得返回无权查看的下游任务"
    )

    _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        code=4001,
        headers=ctx.publisher,
        body={"deadline": "not-a-date"},
        label="PATCH 非法截止时间",
    )
    with SessionLocal() as db:
        stored = db.get(Task, task_id)
        assert stored is not None and stored.deadline != "not-a-date", "非法截止时间不得落库"


def test_equivalent_deadline_format_is_not_a_change(ctx: _Ctx) -> None:
    now = datetime.now().replace(microsecond=0)
    task_id = _create_task(ctx, "AIW05 等价格式", deadline="2030-12-01")

    impact = _ok(
        ctx.client,
        "GET",
        f"/api/tasks/{task_id}/change-impact?deadline=2030-12-01%2000%3A00%3A00",
        headers=ctx.publisher,
        label="等价格式预览",
    )
    assert impact["reminders_reset"] is False

    data = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"deadline": "2030-12-01 00:00:00"},
        label="等价格式改期",
    )
    assert "change" not in data or data["change"] is None, "同一时刻不同写法不应触发变更通知"

    # 空串与 null 同义：按“清除截止”处理。
    cleared = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"deadline": ""},
        label="空串清除截止",
    )
    assert (cleared.get("change") or {}).get("kind") == "deadline"
    assert (cleared.get("change") or {}).get("new_deadline") is None


def test_overdue_prefix_reminders_become_stale(ctx: _Ctx) -> None:
    now = datetime.now().replace(microsecond=0)
    task_id = _create_task(
        ctx, "AIW05 逾期旧提醒", deadline=(now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    )
    reminder_scheduler.scan_and_remind(now=now)
    overdue = [row for row in _notifications(task_id, ctx.worker_id) if (row.dedupe_key or "").startswith("overdue:")]
    assert overdue, "逾期扫描应生成 overdue: 提醒"
    publisher_overdue = [
        row for row in _notifications(task_id, ctx.publisher_id)
        if (row.dedupe_key or "").startswith("overdue_pub:")
    ]
    assert publisher_overdue, "逾期扫描应生成 overdue_pub: 发布者提醒"

    _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"deadline": (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")},
        label="逾期后改期",
    )
    after = _notifications(task_id, ctx.worker_id)
    assert all(row.stale == 1 for row in after if (row.dedupe_key or "").startswith("overdue:"))
    publisher_after = _notifications(task_id, ctx.publisher_id)
    assert all(
        row.stale == 1 for row in publisher_after
        if (row.dedupe_key or "").startswith("overdue_pub:")
    )


def test_same_reschedule_does_not_repeat_notification(ctx: _Ctx) -> None:
    now = datetime.now().replace(microsecond=0)
    task_id = _create_task(ctx, "AIW05 重复改期", deadline=(now + timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S"))
    first = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"deadline": (now + timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S")},
        label="首次改期",
    )
    assert (first.get("change") or {}).get("notifications_created", 0) >= 1
    count = len(
        [row for row in _notifications(task_id, ctx.publisher_id) if (row.dedupe_key or "").startswith("change:deadline:")]
    )

    second = _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"deadline": (now + timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S")},
        label="重复改期",
    )
    assert "change" not in second or second["change"] is None
    after = len(
        [row for row in _notifications(task_id, ctx.publisher_id) if (row.dedupe_key or "").startswith("change:deadline:")]
    )
    assert after == count, "相同值重复 PATCH 不应新增变更通知"


def test_reserved_quota_blocks_concurrent_generation(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """另一请求已原子预留额度时，本请求不得再生成（`C-AI-RESERVATION@2`）。

    旧实现依赖“模型调用后二次额度检查”；该机制已被“模型调用前原子预留”取代，
    此处用一条 pending 预留模拟并发中的另一请求，验证额度争用顺序场景。
    """
    monkeypatch.setenv("AI_DAILY_QUOTA", "1")
    with SessionLocal() as db:
        db.add(
            AiUsageLedger(
                user_id=ctx.worker_id,
                request_id="aiw05-other-pending",
                operation="chat",
                units=1,
                status="pending",
                created_at=datetime.now(),
            )
        )
        db.commit()
    try:
        _err(
            ctx.client,
            "POST",
            "/api/agent/chat",
            code=ERR_QUOTA,
            headers=ctx.worker,
            body={"message": "预留额度检查", "request_id": "aiw05-second-check"},
            label="预留额度检查",
        )
        with SessionLocal() as db:
            assert (
                db.query(AiUsageLedger)
                .filter(AiUsageLedger.request_id == "aiw05-second-check")
                .count()
                == 0
            ), "额度争用失败时不得写入本请求账本"
    finally:
        with SessionLocal() as db:
            db.query(AiUsageLedger).filter(
                AiUsageLedger.request_id == "aiw05-other-pending"
            ).delete()
            db.commit()


def test_real_model_success_writes_settled_ledger(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)
    monkeypatch.setattr(ai_service, "_real_answer", lambda _items, _text: ("真实模型回答", []))
    before = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="真实模型前用量")["used"]
    data = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.worker,
        body={"message": "真实模型路径", "request_id": "aiw05-real-success"},
        label="真实模型成功",
    )
    assert data["mock"] is False
    assert data["assistant_message"]["content"] == "真实模型回答"
    after = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="真实模型后用量")["used"]
    assert after == before + 1
    with SessionLocal() as db:
        row = (
            db.query(AiUsageLedger)
            .filter(AiUsageLedger.request_id == "aiw05-real-success")
            .one()
        )
        assert row.status == "settled" and row.units == 1
        assert row.assistant_message_id is not None


def test_chat_usage_and_replay_are_idempotent(ctx: _Ctx) -> None:
    before_usage = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="首次问答前用量")
    with SessionLocal() as db:
        before_ledger_total = db.query(AiUsageLedger).filter(AiUsageLedger.user_id == ctx.worker_id).count()
    first = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.worker,
        body={"message": "我有哪些任务？", "request_id": "aiw05-req-1"},
        label="首次问答",
    )
    assert first["replayed"] is False
    conversation_id = first["conversation_id"]

    usage = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="用量查询")
    expected_used = before_usage["used"] + 1
    assert usage["used"] == expected_used
    assert usage["limit"] == 50
    assert usage["remaining"] == 50 - expected_used
    assert usage["items"][0]["request_id"] == "aiw05-req-1"

    with SessionLocal() as db:
        message_count = db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).count()
        ledger_count = db.query(AiUsageLedger).filter(AiUsageLedger.request_id == "aiw05-req-1").count()
    assert message_count == 2
    assert ledger_count == 1

    replay = _ok(
        ctx.client,
        "POST",
        "/api/agent/chat",
        headers=ctx.worker,
        body={"message": "我有哪些任务？", "request_id": "aiw05-req-1"},
        label="重放请求",
    )
    assert replay["replayed"] is True
    assert replay["conversation_id"] == conversation_id
    assert replay["assistant_message"]["id"] == first["assistant_message"]["id"]

    usage_after = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="重放后用量")
    assert usage_after["used"] == expected_used, "重放不得重复计费"
    with SessionLocal() as db:
        assert db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).count() == 2
        assert (
            db.query(AiUsageLedger).filter(AiUsageLedger.user_id == ctx.worker_id).count()
            == before_ledger_total + 1
        )

    other = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.outsider, label="他人用量")
    assert other["used"] == 0, "跨账号不得看到或共用他人用量"


def test_zero_quota_blocks_chat_but_not_collaboration(ctx: _Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_DAILY_QUOTA", "0")
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        code=ERR_QUOTA,
        headers=ctx.worker,
        body={"message": "额度测试", "request_id": "aiw05-quota-zero"},
        label="零额度问答",
    )
    usage = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="零额度用量")
    assert usage["limit"] == 0 and usage["remaining"] == 0

    notices = _ok(ctx.client, "GET", "/api/notifications", headers=ctx.worker, label="零额度通知")
    assert isinstance(notices["items"], list)
    tasks = _ok(ctx.client, "GET", "/api/tasks?scope=all", headers=ctx.worker, label="零额度任务")
    assert isinstance(tasks["items"], list)
    with SessionLocal() as db:
        assert db.query(AiUsageLedger).filter(AiUsageLedger.request_id == "aiw05-quota-zero").count() == 0

    # 写协作仍可用：发布者改期不读取 AI 额度。
    now = datetime.now().replace(microsecond=0)
    task_id = _create_task(ctx, "AIW05 零额度改期", deadline=(now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"))
    _ok(
        ctx.client,
        "PATCH",
        f"/api/tasks/{task_id}",
        headers=ctx.publisher,
        body={"deadline": (now + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")},
        label="零额度下改期",
    )


def test_model_failure_does_not_charge_quota(ctx: _Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    before = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="失败前用量")["used"]

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise ApiError(5001, "模拟模型失败")

    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)
    monkeypatch.setattr(ai_service, "_real_answer", _boom)
    _err(
        ctx.client,
        "POST",
        "/api/agent/chat",
        code=5001,
        headers=ctx.worker,
        body={"message": "模型失败", "request_id": "aiw05-model-failure"},
        label="模型失败",
    )
    after = _ok(ctx.client, "GET", "/api/agent/usage", headers=ctx.worker, label="失败后用量")["used"]
    assert after == before, "模型失败不得扣额度"
    with SessionLocal() as db:
        assert db.query(AiUsageLedger).filter(AiUsageLedger.request_id == "aiw05-model-failure").count() == 0