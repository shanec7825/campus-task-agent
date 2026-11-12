#!/usr/bin/env python
"""Phase 1 可靠性回归（R6）：针对已确认缺陷的修复前失败 / 修复后通过用例。

覆盖契约（design.md §2.2）：`C-DATA-MEMBER@1`、`C-MIGRATION@1`、`C-MEMBER@1`、
`C-TASK-API@1`、`C-NOTIFY@1`、`C-TIME-AGENT@1`。

隔离性：在导入 ``app`` 之前即把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立
SQLite 文件，并关闭调度器（``RUN_SCHEDULER=0``）与真实模型（``MAAS_MOCK=1``）。
因此本文件可单独运行：``pytest tests/backend/test_reliability.py``。

覆盖矩阵：
1. 开始时间与提交截止时间独立解析，仅给一方时不伪造另一方；
2. 三成员逐人执行：A 验收通过、B 退回、C 未提交，任务聚合状态与成员状态互不混淆；
3. 重复提交 / 重复验收 / 重复调度 / 重启均幂等；
4. 已提交、已通过、已撤回、已拒绝（非成员）不催办不扣分；
5. 改期后按新截止时间提醒，且不重复扣分、旧历史保留；
6. 逾期后可补交、可验收、可取消，逾期不覆盖成员结果；
7. 旧库增量迁移幂等：补 approved 报名与成员行，不臆造时间戳，不删历史数据；
8. 越权操作 4030 / 目标非法 4001 / 状态冲突 4090。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-reliability-"))
_TEST_DB_PATH = _TMP_DIR / "reliability.db"

# 必须在导入 app 之前完成：app.db 在模块导入时按 DATABASE_PATH 创建引擎。
os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import reminder_scheduler  # noqa: E402

DEADLINE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: 三级催办 level（info 与同级别业务通知不计入催办）
REMINDER_LEVELS = frozenset({"warning", "urgent", "overdue"})

#: 执行催办通知标题（与 reminder_scheduler 文案一致）；级别为 warning 的业务通知
#: （如「报名未通过」「有提交待验收」）不得被误判为催办。
REMINDER_TITLES = frozenset(
    {"任务即将截止", "任务今天截止", "任务已逾期", "成员任务已逾期"}
)

#: 提交时给发布者的通知标题（用于断言重复提交不重复通知）
SUBMIT_NOTIFY_TITLE = "有新任务待验收"

ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_CONFLICT = 4090


# --------------------------------------------------------------------------- #
# 上下文与 HTTP 工具
# --------------------------------------------------------------------------- #
@dataclass
class _Ctx:
    client: TestClient
    teacher: str
    s1: str
    s2: str
    s3: str
    ids: dict[str, int]


def _request(client: TestClient, method: str, path: str, *, token: str | None = None, body: Any = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.request(method, path, json=body, headers=headers)


def _payload(client: TestClient, method: str, path: str, *, token: str | None = None, body: Any = None, label: str = "") -> dict:
    response = _request(client, method, path, token=token, body=body)
    try:
        payload = response.json()
    except ValueError:  # 响应非 JSON（例如未捕获 500）
        raise AssertionError(f"{label}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert isinstance(payload, dict), f"{label}：响应体不是对象（HTTP {response.status_code}）"
    return payload


def _ok(client: TestClient, method: str, path: str, *, token: str | None = None, body: Any = None, label: str = "") -> dict:
    payload = _payload(client, method, path, token=token, body=body, label=label)
    assert payload.get("code") == 0, f"{label}：期望 code=0，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    data = payload.get("data")
    assert isinstance(data, dict), f"{label}：data 不是对象（{type(data).__name__}）"
    return data


def _err(client: TestClient, method: str, path: str, *, code: int, token: str | None = None, body: Any = None, label: str = "", status: int = 200) -> dict:
    response = _request(client, method, path, token=token, body=body)
    payload = response.json()
    assert payload.get("code") == code, f"{label}：期望 code={code}，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    assert response.status_code == status, f"{label}：期望 HTTP {status}，实际 HTTP {response.status_code}"
    return payload


def _login(client: TestClient, username: str) -> tuple[str, dict]:
    data = _ok(client, "POST", "/api/auth/login", body={"username": username}, label=f"登录 {username}")
    token = data.get("token")
    assert isinstance(token, str) and token, f"{username} 未返回 token"
    return token, data["user"]


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        logins: dict[str, tuple[str, dict]] = {
            name: _login(client, name)
            for name in ("teacher01", "student01", "student02", "student03")
        }
        yield _Ctx(
            client=client,
            teacher=logins["teacher01"][0],
            s1=logins["student01"][0],
            s2=logins["student02"][0],
            s3=logins["student03"][0],
            ids={name: int(user["id"]) for name, (_token, user) in logins.items()},
        )


# --------------------------------------------------------------------------- #
# 业务辅助
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _fmt(moment: datetime) -> str:
    return moment.strftime(DEADLINE_FORMAT)


def _create_task(client: TestClient, token: str, title: str, **fields: Any) -> dict:
    return _ok(client, "POST", "/api/tasks", token=token, body={"title": title, **fields}, label=f"发布「{title}」")


def _apply_and_approve(client: TestClient, teacher: str, student: str, task_id: int) -> int:
    applied = _ok(client, "POST", f"/api/tasks/{task_id}/apply", token=student, label=f"报名任务 {task_id}")
    application_id = int(applied["application"]["id"])
    _ok(
        client,
        "POST",
        f"/api/applications/{application_id}/decide",
        token=teacher,
        body={"approve": True},
        label=f"审批通过任务 {task_id}",
    )
    return application_id


def _task(client: TestClient, task_id: int, token: str) -> dict:
    return _ok(client, "GET", f"/api/tasks/{task_id}", token=token, label=f"任务 {task_id} 详情")


def _member(task: dict, user_id: int) -> dict | None:
    for item in task.get("members") or []:
        if int(item.get("user_id") or 0) == int(user_id):
            return item
    return None


def _member_status(task: dict, user_id: int, *, label: str = "") -> str:
    member = _member(task, user_id)
    assert member is not None, f"{label}：TaskOut.members 缺少 user_id={user_id}（members={task.get('members')}）"
    return str(member.get("status"))


def _notifications(client: TestClient, token: str, task_id: int) -> list[dict]:
    data = _ok(client, "GET", "/api/notifications?limit=200", token=token, label="通知列表")
    return [item for item in data.get("items") or [] if int(item.get("task_id") or 0) == int(task_id)]


def _reminders(client: TestClient, token: str, task_id: int) -> list[dict]:
    """只取执行催办：level 属三级且 title 属催办文案（排除业务 warning 通知）。"""
    return [
        item
        for item in _notifications(client, token, task_id)
        if str(item.get("level")) in REMINDER_LEVELS
        and str(item.get("title")) in REMINDER_TITLES
    ]


def _notification_counts(ctx: _Ctx, task_id: int) -> dict[str, int]:
    tokens = {"teacher": ctx.teacher, "s1": ctx.s1, "s2": ctx.s2, "s3": ctx.s3}
    return {name: len(_notifications(ctx.client, token, task_id)) for name, token in tokens.items()}


def _task_logs(client: TestClient, token: str, task_id: int) -> list[dict]:
    data = _ok(client, "GET", "/api/credits/me", token=token, label="积分流水")
    return [log for log in data.get("logs") or [] if int(log.get("task_id") or 0) == int(task_id)]


def _penalties(client: TestClient, token: str, task_id: int) -> list[dict]:
    return [log for log in _task_logs(client, token, task_id) if int(log.get("delta") or 0) < 0]


def _progress(ctx: _Ctx, token: str, task_id: int, content: str) -> dict:
    return _ok(ctx.client, "POST", f"/api/tasks/{task_id}/progress", token=token, body={"content": content}, label=f"任务 {task_id} 进度")


def _submit(ctx: _Ctx, token: str, task_id: int) -> dict:
    return _ok(ctx.client, "POST", f"/api/tasks/{task_id}/submit", token=token, label=f"任务 {task_id} 提交")


def _verify(ctx: _Ctx, task_id: int, *, passed: bool, user_id: int | None = None, reason: str | None = None) -> dict:
    body: dict[str, Any] = {"pass": passed}
    if reason is not None:
        body["reason"] = reason
    if user_id is not None:
        body["user_id"] = int(user_id)
    return _ok(ctx.client, "POST", f"/api/tasks/{task_id}/verify", token=ctx.teacher, body=body, label=f"任务 {task_id} 验收")


# --------------------------------------------------------------------------- #
# 1. R1：开始时间与截止时间独立，且不伪造截止
# --------------------------------------------------------------------------- #
def test_start_and_deadline_are_independent(ctx: _Ctx) -> None:
    both = _ok(
        ctx.client,
        "POST",
        "/api/agent/extract",
        token=ctx.teacher,
        body={"text": "秋之韵招募，明天下午两点在教三集合，五点前提交材料"},
        label="extract 同时含开始与截止",
    )
    draft = both["draft"]
    assert draft.get("time") == "明天下午两点", f"开始时间独立解析（实际 {draft.get('time')!r}）"
    assert draft.get("deadline") == "五点", f"截止时间独立解析（实际 {draft.get('deadline')!r}）"
    assert draft.get("time") != draft.get("deadline"), "开始时间与截止时间不得互相复制"
    assert any(span.get("field") == "deadline" and span.get("text") == "五点" for span in both.get("spans") or []), (
        f"spans 中截止语义词归属 field=deadline（实际 {[(s.get('field'), s.get('text')) for s in both.get('spans') or []]}）"
    )

    start_only = _ok(
        ctx.client,
        "POST",
        "/api/agent/extract",
        token=ctx.teacher,
        body={"text": "秋之韵招募，明天下午两点在教三集合"},
        label="extract 仅开始时间",
    )["draft"]
    assert start_only.get("time") == "明天下午两点", "仅给开始时间时 time 命中"
    assert start_only.get("deadline") is None, f"仅给开始时间不得伪造截止（实际 {start_only.get('deadline')!r}）"

    deadline_only = _ok(
        ctx.client,
        "POST",
        "/api/agent/extract",
        token=ctx.teacher,
        body={"text": "秋之韵招募，五点前提交材料"},
        label="extract 仅截止时间",
    )["draft"]
    assert deadline_only.get("deadline") == "五点", f"仅给截止时间时 deadline 命中（实际 {deadline_only.get('deadline')!r}）"
    assert deadline_only.get("time") is None, f"仅给截止时间不得写回开始时间（实际 {deadline_only.get('time')!r}）"

    start_task = _create_task(ctx.client, ctx.teacher, "R1 仅开始时间任务", start_time="2026-12-01 08:00:00")
    assert start_task.get("start_time") == "2026-12-01 08:00:00", "发布后 start_time 独立保存"
    assert start_task.get("deadline") is None, f"仅提供开始时间时 tasks.deadline 保持空（实际 {start_task.get('deadline')!r}）"

    deadline_task = _create_task(ctx.client, ctx.teacher, "R1 仅截止时间任务", deadline="2026-12-02 18:00:00")
    assert deadline_task.get("deadline") == "2026-12-02 18:00:00", "发布后 deadline 独立保存"
    assert deadline_task.get("start_time") is None, f"仅提供截止时间时 tasks.start_time 保持空（实际 {deadline_task.get('start_time')!r}）"


# --------------------------------------------------------------------------- #
# 2. R2：三成员逐人执行（A 通过 / B 退回 / C 未提交）与越权拦截
# --------------------------------------------------------------------------- #
def test_three_members_verify_reject_and_pending(ctx: _Ctx) -> None:
    task = _create_task(ctx.client, ctx.teacher, "R2 三成员逐人验收任务", quota=3, credit_reward=15)
    task_id = task["id"]
    for token in (ctx.s1, ctx.s2, ctx.s3):
        _apply_and_approve(ctx.client, ctx.teacher, token, task_id)

    _progress(ctx, ctx.s1, task_id, "A 进度")
    _progress(ctx, ctx.s2, task_id, "B 进度")

    detail = _task(ctx.client, task_id, ctx.teacher)
    assert _member_status(detail, ctx.ids["student01"]) == "in_progress", "A 进度后仅 A 成员状态变化"
    assert _member_status(detail, ctx.ids["student02"]) == "in_progress", "B 进度后 B 成员状态变化"
    assert _member_status(detail, ctx.ids["student03"]) == "not_started", "C 未操作保持 not_started"

    _submit(ctx, ctx.s1, task_id)
    _submit(ctx, ctx.s2, task_id)
    detail = _task(ctx.client, task_id, ctx.teacher)
    assert _member_status(detail, ctx.ids["student01"]) == "submitted", "A 提交后仅 A 为 submitted"
    assert _member_status(detail, ctx.ids["student02"]) == "submitted", "B 提交后 B 为 submitted"
    assert _member_status(detail, ctx.ids["student03"]) == "not_started", "C 未提交保持 not_started"
    assert detail.get("status") == "submitted", f"至少一人待验收时任务聚合 submitted（实际 {detail.get('status')}）"
    assert _task(ctx.client, task_id, ctx.s3).get("my_member_status") == "not_started", (
        "C 的 my_member_status 为 not_started，不得由任务状态推断"
    )

    # 重复提交：幂等 200，且不新增发布者通知
    submit_notify_before = [
        item for item in _notifications(ctx.client, ctx.teacher, task_id) if item.get("title") == SUBMIT_NOTIFY_TITLE
    ]
    assert len(submit_notify_before) == 2, f"两名成员各产生 1 条提交通知（实际 {len(submit_notify_before)}）"
    _submit(ctx, ctx.s1, task_id)
    submit_notify_after = [
        item for item in _notifications(ctx.client, ctx.teacher, task_id) if item.get("title") == SUBMIT_NOTIFY_TITLE
    ]
    assert len(submit_notify_after) == 2, f"重复提交不新增提交通知（实际 {len(submit_notify_after)}）"

    # A 验收通过：只改 A 的成员状态与积分
    a_logs_before = len(_task_logs(ctx.client, ctx.s1, task_id))
    verified = _verify(ctx, task_id, passed=True, user_id=ctx.ids["student01"])
    assert verified.get("credit_delta") == 15, f"A 通过奖励 15（实际 {verified.get('credit_delta')}）"
    assert verified.get("credited_user_ids") == [ctx.ids["student01"]], f"仅 A 加分（实际 {verified.get('credited_user_ids')}）"
    detail = _task(ctx.client, task_id, ctx.teacher)
    assert _member_status(detail, ctx.ids["student01"]) == "verified", "A 成员状态 verified"
    assert _member_status(detail, ctx.ids["student02"]) == "submitted", "B 成员状态不受 A 验收影响"
    assert _member_status(detail, ctx.ids["student03"]) == "not_started", "C 成员状态不受 A 验收影响"
    assert detail.get("status") == "submitted", "仍有成员待验收时任务聚合保持 submitted"
    assert len(_task_logs(ctx.client, ctx.s1, task_id)) == a_logs_before + 1, "A 仅产生 1 条积分流水"

    # 重复验收：4090 且不新增流水
    _err(ctx.client, "POST", f"/api/tasks/{task_id}/verify", code=ERR_CONFLICT, token=ctx.teacher, body={"pass": True, "user_id": ctx.ids["student01"]}, label="重复验收已通过成员 4090")
    assert len(_task_logs(ctx.client, ctx.s1, task_id)) == a_logs_before + 1, "重复验收不新增积分流水"

    # B 退回：只改 B，任务回到 in_progress，A 的 verified 保留
    rejected = _verify(ctx, task_id, passed=False, user_id=ctx.ids["student02"], reason="物料缺失")
    assert rejected.get("credit_delta") == 0, "退回不加分"
    detail = _task(ctx.client, task_id, ctx.teacher)
    assert _member_status(detail, ctx.ids["student02"]) == "rejected", "B 成员状态 rejected"
    assert (_member(detail, ctx.ids["student02"]) or {}).get("rejection_reason") == "物料缺失", "退回原因落库"
    assert _member_status(detail, ctx.ids["student01"]) == "verified", "B 退回不覆盖 A 的 verified"
    assert detail.get("status") == "in_progress", f"存在退回成员时任务聚合 in_progress（实际 {detail.get('status')}）"

    # 目标非法：C 未提交 4090；非成员 4001；非发布者 4030
    _err(ctx.client, "POST", f"/api/tasks/{task_id}/verify", code=ERR_CONFLICT, token=ctx.teacher, body={"pass": True, "user_id": ctx.ids["student03"]}, label="验收未提交成员 4090")
    _err(ctx.client, "POST", f"/api/tasks/{task_id}/verify", code=ERR_INVALID_PARAM, token=ctx.teacher, body={"pass": True, "user_id": 999999}, label="验收非成员 4001")
    _err(ctx.client, "POST", f"/api/tasks/{task_id}/verify", code=ERR_FORBIDDEN, token=ctx.s1, body={"pass": True}, label="非发布者验收 4030")

    # 越权：非成员不能提交 / 记录进度
    _err(ctx.client, "POST", f"/api/tasks/{task_id}/submit", code=ERR_FORBIDDEN, token=ctx.teacher, label="非成员提交 4030")
    _err(ctx.client, "POST", f"/api/tasks/{task_id}/progress", code=ERR_FORBIDDEN, token=ctx.teacher, body={"content": "非成员进度"}, label="非成员进度 4030")

    # B 退回后可重新提交并验收通过（逐人语义）
    _submit(ctx, ctx.s2, task_id)
    detail = _task(ctx.client, task_id, ctx.teacher)
    assert _member_status(detail, ctx.ids["student02"]) == "submitted", "退回成员可重新提交"
    b_logs_before = len(_task_logs(ctx.client, ctx.s2, task_id))
    _verify(ctx, task_id, passed=True, user_id=ctx.ids["student02"])
    detail = _task(ctx.client, task_id, ctx.teacher)
    assert _member_status(detail, ctx.ids["student02"]) == "verified", "B 重新验收通过"
    assert len(_task_logs(ctx.client, ctx.s2, task_id)) == b_logs_before + 1, "B 仅加一次积分"
    assert detail.get("status") != "verified", "C 未完成时任务聚合不得为 verified"
    assert _member_status(detail, ctx.ids["student03"]) == "not_started", "C 始终 not_started"


# --------------------------------------------------------------------------- #
# 3. R3：仅为未完成成员催办；重复扫描与重启幂等
# --------------------------------------------------------------------------- #
def test_reminder_skips_finished_members_and_is_idempotent(ctx: _Ctx) -> None:
    now = _now()
    task = _create_task(
        ctx.client,
        ctx.teacher,
        "R3 分级催办成员过滤任务",
        quota=3,
        credit_reward=10,
        deadline=_fmt(now + timedelta(hours=5)),
        reminder_rule={"days_before": 3, "day_of": True, "on_overdue": True},
    )
    task_id = task["id"]
    for token in (ctx.s1, ctx.s2, ctx.s3):
        _apply_and_approve(ctx.client, ctx.teacher, token, task_id)

    # A 已完成（验收通过）、B 进行中、C 未开始
    _progress(ctx, ctx.s1, task_id, "A 进度")
    _submit(ctx, ctx.s1, task_id)
    _verify(ctx, task_id, passed=True, user_id=ctx.ids["student01"])
    _progress(ctx, ctx.s2, task_id, "B 进度")

    detail = _task(ctx.client, task_id, ctx.teacher)
    assert _member_status(detail, ctx.ids["student01"]) == "verified", "A 已通过"
    assert _member_status(detail, ctx.ids["student02"]) == "in_progress", "B 进行中"
    assert _member_status(detail, ctx.ids["student03"]) == "not_started", "C 未开始"

    reminder_scheduler.scan_and_remind(now=now)

    assert _reminders(ctx.client, ctx.s1, task_id) == [], "已通过成员不催办"
    assert len(_reminders(ctx.client, ctx.s2, task_id)) == 1, f"进行中成员收到 1 条催办（实际 {len(_reminders(ctx.client, ctx.s2, task_id))}）"
    assert len(_reminders(ctx.client, ctx.s3, task_id)) == 1, f"未开始成员收到 1 条催办（实际 {len(_reminders(ctx.client, ctx.s3, task_id))}）"
    assert [item.get("level") for item in _reminders(ctx.client, ctx.s2, task_id)] == ["urgent"], (
        f"5 小时内截止为 urgent（实际 {[item.get('level') for item in _reminders(ctx.client, ctx.s2, task_id)]}）"
    )

    snapshot = _notification_counts(ctx, task_id)
    assert reminder_scheduler.scan_and_remind(now=now) == 0, "重复扫描不新增通知"
    assert _notification_counts(ctx, task_id) == snapshot, "重复扫描后通知数量不变"

    # 进程重启：再次执行启动迁移后扫描仍不重复
    init_db()
    assert reminder_scheduler.scan_and_remind(now=now) == 0, "重启后扫描不新增通知"
    assert _notification_counts(ctx, task_id) == snapshot, "重启后通知数量不变"
    assert _member_status(_task(ctx.client, task_id, ctx.teacher), ctx.ids["student01"]) == "verified", "重启不覆盖成员验收结果"


# --------------------------------------------------------------------------- #
# 4. R3：逾期逐成员一次性扣分；已撤回/已拒绝申请不催办不扣分
# --------------------------------------------------------------------------- #
def test_overdue_penalty_once_per_member(ctx: _Ctx) -> None:
    now = _now()
    deadline = _fmt(now - timedelta(hours=1))
    task = _create_task(
        ctx.client,
        ctx.teacher,
        "R3 逐成员逾期扣分任务",
        quota=2,
        credit_reward=10,
        deadline=deadline,
        reminder_rule={"days_before": 2, "day_of": True, "on_overdue": True},
    )
    task_id = task["id"]
    _apply_and_approve(ctx.client, ctx.teacher, ctx.s2, task_id)
    _apply_and_approve(ctx.client, ctx.teacher, ctx.s3, task_id)

    _progress(ctx, ctx.s2, task_id, "已提交成员进度")
    _submit(ctx, ctx.s2, task_id)
    _progress(ctx, ctx.s3, task_id, "未完成成员进度")

    # 撤回的报名（s1）与拒绝的报名（s3 的另一任务）都不是成员
    ghost = _create_task(
        ctx.client,
        ctx.teacher,
        "R3 撤回与拒绝申请不催办任务",
        quota=3,
        deadline=deadline,
        reminder_rule={"days_before": 2, "day_of": True, "on_overdue": True},
    )
    ghost_id = ghost["id"]
    _ok(ctx.client, "POST", f"/api/tasks/{ghost_id}/apply", token=ctx.s1, label="撤回用例报名")
    _ok(ctx.client, "POST", f"/api/tasks/{ghost_id}/apply/withdraw", token=ctx.s1, label="撤回报名")
    rejected_app = _ok(ctx.client, "POST", f"/api/tasks/{ghost_id}/apply", token=ctx.s3, label="拒绝用例报名")
    _ok(
        ctx.client,
        "POST",
        f"/api/applications/{rejected_app['application']['id']}/decide",
        token=ctx.teacher,
        body={"approve": False, "reason": "时间冲突"},
        label="拒绝报名",
    )

    reminder_scheduler.scan_and_remind(now=now)

    detail = _task(ctx.client, task_id, ctx.teacher)
    assert detail.get("status") == "overdue", f"逾期任务状态置 overdue（实际 {detail.get('status')}）"
    assert _member_status(detail, ctx.ids["student02"]) == "submitted", "逾期不覆盖已提交成员结果"
    assert _member_status(detail, ctx.ids["student03"]) == "in_progress", "逾期不覆盖进行中成员结果"

    assert _reminders(ctx.client, ctx.s2, task_id) == [], "已提交成员不催办"
    assert _penalties(ctx.client, ctx.s2, task_id) == [], "已提交成员不扣分"
    assert len(_reminders(ctx.client, ctx.s3, task_id)) == 1, f"未完成成员收到 1 条逾期催办（实际 {len(_reminders(ctx.client, ctx.s3, task_id))}）"
    assert len(_penalties(ctx.client, ctx.s3, task_id)) == 1, "未完成成员扣分一次"

    for token in (ctx.s1, ctx.s3):
        assert _reminders(ctx.client, token, ghost_id) == [], "撤回/拒绝的申请人不催办"
        assert _penalties(ctx.client, token, ghost_id) == [], "撤回/拒绝的申请人不扣分"

    snapshot = _notification_counts(ctx, task_id)
    assert reminder_scheduler.scan_and_remind(now=now) == 0, "重复扫描不新增通知"
    assert len(_penalties(ctx.client, ctx.s3, task_id)) == 1, "重复扫描不重复扣分"
    init_db()
    assert reminder_scheduler.scan_and_remind(now=now) == 0, "重启后扫描不新增通知"
    assert len(_penalties(ctx.client, ctx.s3, task_id)) == 1, "重启不重复扣分"
    assert _notification_counts(ctx, task_id) == snapshot, "重启后通知数量不变"


# --------------------------------------------------------------------------- #
# 5. R4：改期后按新截止时间提醒，不重复扣分，旧历史保留
# --------------------------------------------------------------------------- #
def test_deadline_extension_reminds_on_new_deadline(ctx: _Ctx) -> None:
    now = _now()
    task = _create_task(
        ctx.client,
        ctx.teacher,
        "R4 改期后新截止提醒任务",
        quota=2,
        credit_reward=10,
        deadline=_fmt(now - timedelta(hours=1)),
        reminder_rule={"days_before": 3, "day_of": True, "on_overdue": True},
    )
    task_id = task["id"]
    _apply_and_approve(ctx.client, ctx.teacher, ctx.s1, task_id)
    _apply_and_approve(ctx.client, ctx.teacher, ctx.s2, task_id)

    _progress(ctx, ctx.s1, task_id, "未完成成员进度")
    _progress(ctx, ctx.s2, task_id, "已完成成员进度")
    _submit(ctx, ctx.s2, task_id)
    _verify(ctx, task_id, passed=True, user_id=ctx.ids["student02"])

    reminder_scheduler.scan_and_remind(now=now)

    old_reminders = _reminders(ctx.client, ctx.s1, task_id)
    assert len(old_reminders) == 1 and old_reminders[0].get("level") == "overdue", f"首次扫描为 overdue（实际 {[i.get('level') for i in old_reminders]}）"
    assert len(_penalties(ctx.client, ctx.s1, task_id)) == 1, "首次逾期扣分一次"
    assert _reminders(ctx.client, ctx.s2, task_id) == [], "已通过成员不催办"
    assert _penalties(ctx.client, ctx.s2, task_id) == [], "已通过成员不扣分"
    assert _task(ctx.client, task_id, ctx.teacher).get("status") == "overdue", "首次扫描后任务 overdue"

    # 发布者改期到未来：状态由 overdue 拉回，提醒按新截止时间版本重新生成
    new_deadline = _fmt(now + timedelta(days=2))
    updated = _ok(ctx.client, "PATCH", f"/api/tasks/{task_id}", token=ctx.teacher, body={"deadline": new_deadline}, label="修改截止时间")
    assert updated.get("deadline") == new_deadline, "截止时间保存为新值"
    assert updated.get("status") == "in_progress", f"改期后按成员状态重算聚合（实际 {updated.get('status')}）"

    reminder_scheduler.scan_and_remind(now=now)

    current_reminders = _reminders(ctx.client, ctx.s1, task_id)
    assert len(current_reminders) == 2, f"改期后新增一条提醒且保留旧历史（实际 {len(current_reminders)}）"
    assert any(item.get("level") == "warning" for item in current_reminders), "新截止时间落在预警窗口内产生 warning"
    assert len(_penalties(ctx.client, ctx.s1, task_id)) == 1, "改期不重复扣分（历史扣分不退还）"
    assert _reminders(ctx.client, ctx.s2, task_id) == [], "改期不为已通过成员催办"

    snapshot = _notification_counts(ctx, task_id)
    assert reminder_scheduler.scan_and_remind(now=now) == 0, "新截止时间同样去重"
    assert _notification_counts(ctx, task_id) == snapshot, "重复扫描通知数量不变"


# --------------------------------------------------------------------------- #
# 6. R4：逾期后可补交、可验收、可取消
# --------------------------------------------------------------------------- #
def test_overdue_late_submission_verify_and_cancel(ctx: _Ctx) -> None:
    now = _now()
    task = _create_task(
        ctx.client,
        ctx.teacher,
        "R4 逾期补交与取消任务",
        quota=2,
        credit_reward=10,
        deadline=_fmt(now - timedelta(hours=1)),
        reminder_rule={"days_before": 2, "day_of": True, "on_overdue": True},
    )
    task_id = task["id"]
    _apply_and_approve(ctx.client, ctx.teacher, ctx.s1, task_id)
    _apply_and_approve(ctx.client, ctx.teacher, ctx.s2, task_id)

    reminder_scheduler.scan_and_remind(now=now)
    assert _task(ctx.client, task_id, ctx.teacher).get("status") == "overdue", "首次扫描后任务 overdue"
    assert len(_penalties(ctx.client, ctx.s1, task_id)) == 1, "逾期成员被扣分一次"

    # 逾期后仍可推进并补交
    _progress(ctx, ctx.s1, task_id, "逾期后补进度")
    _submit(ctx, ctx.s1, task_id)
    detail = _task(ctx.client, task_id, ctx.teacher)
    assert _member_status(detail, ctx.ids["student01"]) == "submitted", "逾期后仍可补交"
    assert detail.get("status") == "submitted", f"补交后任务从 overdue 回到 submitted（实际 {detail.get('status')}）"

    # 逾期补交可验收，积分照常
    logs_before = len(_task_logs(ctx.client, ctx.s1, task_id))
    _verify(ctx, task_id, passed=True, user_id=ctx.ids["student01"])
    detail = _task(ctx.client, task_id, ctx.teacher)
    assert _member_status(detail, ctx.ids["student01"]) == "verified", "逾期补交可验收通过"
    assert len(_task_logs(ctx.client, ctx.s1, task_id)) == logs_before + 1, "逾期补交验收加分一次"

    # 改期后另一名成员仍可继续
    _ok(ctx.client, "PATCH", f"/api/tasks/{task_id}", token=ctx.teacher, body={"deadline": _fmt(now + timedelta(days=1))}, label="改期继续执行")
    _progress(ctx, ctx.s2, task_id, "改期后进度")

    # 取消：逾期任务仍可取消，取消后不再受理成员操作
    cancelled = _ok(ctx.client, "PATCH", f"/api/tasks/{task_id}", token=ctx.teacher, body={"status": "cancelled"}, label="取消任务")
    assert cancelled.get("status") == "cancelled", "发布者可取消任务"
    _err(ctx.client, "POST", f"/api/tasks/{task_id}/submit", code=ERR_CONFLICT, token=ctx.s2, label="取消后提交 4090")
    _err(ctx.client, "POST", f"/api/tasks/{task_id}/verify", code=ERR_CONFLICT, token=ctx.teacher, body={"pass": True, "user_id": ctx.ids["student01"]}, label="取消后验收 4090")

    snapshot = _notification_counts(ctx, task_id)
    reminder_scheduler.scan_and_remind(now=now)
    assert _notification_counts(ctx, task_id) == snapshot, "取消任务不再催办"
    assert len(_penalties(ctx.client, ctx.s2, task_id)) == 1, "取消不重复扣分"


# --------------------------------------------------------------------------- #
# 7. R5：旧库增量迁移幂等
# --------------------------------------------------------------------------- #
def _build_legacy_db(path: Path) -> None:
    """构造 P1 形态的旧库：缺 ``notifications.dedupe_key``、无 ``task_members``。"""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'published',
                publisher_id INTEGER NOT NULL,
                assignee_id INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE task_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                reason TEXT,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                decided_by INTEGER,
                CONSTRAINT uq_task_applications_task_user UNIQUE (task_id, user_id)
            );
            CREATE TABLE notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_id INTEGER,
                level TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        legacy_tasks = [
            (1, "legacy-verified", "verified", 10, 1),
            (2, "legacy-submitted", "submitted", 10, 2),
            (3, "legacy-in-progress", "in_progress", 10, 3),
            (4, "legacy-claimed", "claimed", 10, 4),
            (5, "legacy-with-approved-application", "in_progress", 10, None),
        ]
        conn.executemany(
            "INSERT INTO tasks (id, title, status, publisher_id, assignee_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(task_id, title, status, publisher, assignee, "2025-12-01 09:00:00") for task_id, title, status, publisher, assignee in legacy_tasks],
        )
        conn.execute(
            "INSERT INTO task_applications (task_id, user_id, status, reason, created_at, decided_at, decided_by) "
            "VALUES (5, 5, 'approved', NULL, '2025-12-02 09:00:00', '2025-12-02 10:00:00', 10)"
        )
        conn.execute(
            "INSERT INTO notifications (user_id, task_id, level, title, content, is_read, created_at) "
            "VALUES (1, 1, 'info', '历史通知', '迁移前已有通知不得修改', 0, '2025-12-03 09:00:00')"
        )
        conn.commit()
    finally:
        conn.close()


def _run_init_db(path: Path) -> None:
    env = dict(os.environ)
    env["DATABASE_PATH"] = str(path)
    result = subprocess.run(
        [sys.executable, "-c", "from app.db import init_db; init_db()"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"init_db 子进程失败（exit={result.returncode}）：{(result.stderr or '')[-1000:]}"


def _columns(path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


def _index_names(path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA index_list({table})").fetchall()}
    finally:
        conn.close()


def _snapshot(path: Path) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(path)
    try:
        rows = {
            "tasks": conn.execute("SELECT id, title, status, assignee_id FROM tasks ORDER BY id").fetchall(),
            "applications": conn.execute(
                "SELECT task_id, user_id, status FROM task_applications ORDER BY task_id, user_id"
            ).fetchall(),
            "members": conn.execute(
                "SELECT task_id, user_id, status, rejection_reason, submitted_at, verified_at "
                "FROM task_members ORDER BY task_id, user_id"
            ).fetchall(),
            "notifications": conn.execute(
                "SELECT id, user_id, task_id, level, title, dedupe_key FROM notifications ORDER BY id"
            ).fetchall(),
        }
    finally:
        conn.close()
    return rows


def _application_rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT task_id, user_id, status, decided_at, decided_by "
            "FROM task_applications ORDER BY task_id, user_id"
        ).fetchall()
    finally:
        conn.close()


def test_legacy_database_migration_is_idempotent(tmp_path: Path) -> None:
    legacy_db = tmp_path / "legacy.db"
    _build_legacy_db(legacy_db)

    _run_init_db(legacy_db)
    first = _snapshot(legacy_db)

    assert "dedupe_key" in _columns(legacy_db, "notifications"), "旧库补齐 notifications.dedupe_key 列"
    assert "uq_notifications_dedupe_key" in _index_names(legacy_db, "notifications"), "建立通知去重唯一索引"
    assert "uq_task_members_task_user" in _index_names(legacy_db, "task_members"), "成员表具备 (task_id,user_id) 唯一约束"

    approved_applications = [(task_id, user_id) for task_id, user_id, status in first["applications"] if status == "approved"]
    assert sorted(approved_applications) == [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)], (
        f"legacy 任务补齐 approved 报名且不重复（实际 {approved_applications}）"
    )

    application_rows = _application_rows(legacy_db)
    backfilled_rows = [row for row in application_rows if int(row[0]) in {1, 2, 3, 4}]
    assert [(row[0], row[2]) for row in backfilled_rows] == [
        (1, "approved"),
        (2, "approved"),
        (3, "approved"),
        (4, "approved"),
    ], f"回填报名状态为 approved（实际 {backfilled_rows}）"
    assert all(row[3] is None and row[4] is None for row in backfilled_rows), (
        f"回填报名的 decided_at/decided_by 保持 NULL，迁移不臆造审批人与审批时间（实际 {backfilled_rows}）"
    )
    existing_row = next(row for row in application_rows if int(row[0]) == 5)
    assert existing_row[3] is not None and existing_row[4] is not None, "既有 approved 报名的审批信息不被迁移覆盖"

    members = {(task_id, user_id): (status, rejection_reason, submitted_at, verified_at) for task_id, user_id, status, rejection_reason, submitted_at, verified_at in first["members"]}
    assert sorted(members) == [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)], f"每个 approved 成员补一行 task_members（实际 {sorted(members)}）"
    assert {key: value[0] for key, value in members.items()} == {
        (1, 1): "verified",
        (2, 2): "submitted",
        (3, 3): "in_progress",
        (4, 4): "not_started",
        (5, 5): "in_progress",
    }, f"成员状态按 tasks.status 一次性映射（实际 { {k: v[0] for k, v in members.items()} }）"
    for key, (_status, rejection_reason, submitted_at, verified_at) in members.items():
        assert rejection_reason is None, f"迁移不臆造退回原因（{key}）"
        assert submitted_at is None and verified_at is None, f"迁移不臆造提交/验收时间（{key}）"

    notifications = first["notifications"]
    assert len(notifications) == 1 and notifications[0][4] == "历史通知", "历史通知保留且唯一"
    assert notifications[0][5] is None, "历史通知的 dedupe_key 保持空"
    assert len(first["tasks"]) == 5, "迁移不删除任务行"

    _run_init_db(legacy_db)
    second = _snapshot(legacy_db)
    assert second == first, "重复 init_db 不产生重复行（幂等）"
    assert sorted({row[0] for row in first["applications"] if row[0] == 4}) == [4], "legacy 报名只补一次"

# --------------------------------------------------------------------------- #
# 8. 独立审查修复回归：终态审批、自我指派、零积分验收
# --------------------------------------------------------------------------- #
def test_terminal_approval_self_assign_and_zero_reward_guards(ctx: _Ctx) -> None:
    teacher_id = ctx.ids["teacher01"]

    # (1) 任务取消后，pending 报名不得再被审批通过（终态守卫）
    cancelled_task = _create_task(ctx.client, ctx.teacher, "审查回归 终态审批任务", quota=2, credit_reward=10)
    cancelled_id = cancelled_task["id"]
    applied = _ok(ctx.client, "POST", f"/api/tasks/{cancelled_id}/apply", token=ctx.s3, label="终态审批用例报名")
    _ok(ctx.client, "PATCH", f"/api/tasks/{cancelled_id}", token=ctx.teacher, body={"status": "cancelled"}, label="取消任务（含 pending 报名）")
    _err(
        ctx.client,
        "POST",
        f"/api/applications/{applied['application']['id']}/decide",
        code=ERR_CONFLICT,
        token=ctx.teacher,
        body={"approve": True},
        label="取消后审批通过 pending 报名 4090",
    )
    cancelled_detail = _task(ctx.client, cancelled_id, ctx.teacher)
    assert cancelled_detail.get("status") == "cancelled", f"审批失败后任务仍为 cancelled（实际 {cancelled_detail.get('status')}）"
    assert all(int(item.get("user_id") or 0) != ctx.ids["student03"] for item in cancelled_detail.get("members") or []), (
        f"审批失败后该学生不得成为成员（实际 members={cancelled_detail.get('members')}）"
    )
    assert _task(ctx.client, cancelled_id, ctx.s3).get("my_member_status") is None, "非成员 my_member_status 为空"
    applications = _ok(ctx.client, "GET", f"/api/tasks/{cancelled_id}/applications", token=ctx.teacher, label="终态审批用例报名列表")
    assert [item.get("status") for item in applications.get("items") or []] == ["pending"], (
        f"报名仍为 pending（实际 {[item.get('status') for item in applications.get('items') or []]}）"
    )

    # (2) 发布者不得把自己指派为执行人（创建 / 指派 / PATCH 三条入口）
    _err(
        ctx.client,
        "POST",
        "/api/tasks",
        code=ERR_FORBIDDEN,
        token=ctx.teacher,
        body={"title": "审查回归 自我指派创建任务", "claim_type": "assign", "assignee_id": teacher_id},
        label="创建任务指派自己 4030",
    )
    assign_task = _create_task(ctx.client, ctx.teacher, "审查回归 自我指派任务", quota=2)
    assign_id = assign_task["id"]
    _err(
        ctx.client,
        "POST",
        f"/api/tasks/{assign_id}/assign",
        code=ERR_FORBIDDEN,
        token=ctx.teacher,
        body={"user_id": teacher_id},
        label="指派接口指派自己 4030",
    )
    _err(
        ctx.client,
        "PATCH",
        f"/api/tasks/{assign_id}",
        code=ERR_FORBIDDEN,
        token=ctx.teacher,
        body={"assignee_id": teacher_id},
        label="PATCH assignee_id 指派自己 4030",
    )
    assign_detail = _task(ctx.client, assign_id, ctx.teacher)
    assert assign_detail.get("assignee_id") is None, f"失败指派不落库（实际 assignee_id={assign_detail.get('assignee_id')}）"
    assert assign_detail.get("status") == "published", "失败指派不改变任务状态"

    # (3) credit_reward=0：验收通过但不得回退为默认奖励
    zero_task = _create_task(ctx.client, ctx.teacher, "审查回归 零积分任务", quota=1, credit_reward=0)
    zero_id = zero_task["id"]
    _apply_and_approve(ctx.client, ctx.teacher, ctx.s2, zero_id)
    _progress(ctx, ctx.s2, zero_id, "零积分任务进度")
    _submit(ctx, ctx.s2, zero_id)
    zero_verified = _verify(ctx, zero_id, passed=True, user_id=ctx.ids["student02"])
    assert zero_verified.get("credit_delta") == 0, f"零奖励任务 credit_delta=0（实际 {zero_verified.get('credit_delta')}）"
    assert zero_verified.get("credited_user_ids") == [ctx.ids["student02"]], (
        f"零奖励任务仍记录通过成员（实际 {zero_verified.get('credited_user_ids')}）"
    )
    zero_detail = _task(ctx.client, zero_id, ctx.teacher)
    assert zero_detail.get("status") == "verified", f"单成员验收后任务 verified（实际 {zero_detail.get('status')}）"
    assert _member_status(zero_detail, ctx.ids["student02"]) == "verified", "零奖励不影响成员验收状态"
    zero_logs = _task_logs(ctx.client, ctx.s2, zero_id)
    assert not [log for log in zero_logs if int(log.get("delta") or 0) > 0], (
        f"零奖励任务不得出现正积分流水（实际 {zero_logs}）"
    )


# --------------------------------------------------------------------------- #
# 9. 复审补充：verified 终态审批、历史自验收、截止时间清空
# --------------------------------------------------------------------------- #
def test_verified_task_rejects_pending_approval(ctx: _Ctx) -> None:
    """任务进入终态 verified 后，pending 报名不得再被审批为 approved。"""
    task = _create_task(ctx.client, ctx.teacher, "复审回归 verified 终态审批任务", quota=2, credit_reward=10)
    task_id = task["id"]
    member_app = _ok(ctx.client, "POST", f"/api/tasks/{task_id}/apply", token=ctx.s1, label="verified 终态用例：成员报名")
    pending_app = _ok(ctx.client, "POST", f"/api/tasks/{task_id}/apply", token=ctx.s3, label="verified 终态用例：待审批报名")
    _ok(
        ctx.client,
        "POST",
        f"/api/applications/{member_app['application']['id']}/decide",
        token=ctx.teacher,
        body={"approve": True},
        label="verified 终态用例：通过成员报名",
    )
    _progress(ctx, ctx.s1, task_id, "verified 终态用例进度")
    _submit(ctx, ctx.s1, task_id)
    _verify(ctx, task_id, passed=True, user_id=ctx.ids["student01"])

    detail = _task(ctx.client, task_id, ctx.teacher)
    assert detail.get("status") == "verified", f"唯一成员验收后任务 verified（实际 {detail.get('status')}）"

    _err(
        ctx.client,
        "POST",
        f"/api/applications/{pending_app['application']['id']}/decide",
        code=ERR_CONFLICT,
        token=ctx.teacher,
        body={"approve": True},
        label="verified 任务审批 pending 报名 4090",
    )
    detail = _task(ctx.client, task_id, ctx.teacher)
    assert detail.get("status") == "verified", f"审批失败后任务仍 verified（实际 {detail.get('status')}）"
    member_ids = [int(item.get("user_id") or 0) for item in detail.get("members") or []]
    assert ctx.ids["student03"] not in member_ids, f"pending 报名不得变成成员（实际 members={member_ids}）"

    applications = _ok(ctx.client, "GET", f"/api/tasks/{task_id}/applications", token=ctx.teacher, label="verified 终态用例报名列表")
    pending_row = next(
        (item for item in applications.get("items") or [] if int(item.get("user_id") or 0) == ctx.ids["student03"]),
        None,
    )
    assert pending_row is not None and pending_row.get("status") == "pending", f"该报名仍为 pending（实际 {pending_row}）"


def _insert_historical_self_assignment(title: str, user_id: int) -> int:
    """SQL 直写 P1 历史数据：发布者即执行人，且已有一条 submitted 成员行（唯一允许的直写）。"""
    conn = sqlite3.connect(str(_TEST_DB_PATH))
    try:
        cursor = conn.execute(
            "INSERT INTO tasks (title, status, claim_type, publisher_id, assignee_id, extras, credit_reward) "
            "VALUES (?, 'submitted', 'assign', ?, ?, '{}', 10)",
            (title, user_id, user_id),
        )
        task_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO task_applications (task_id, user_id, status, created_at, decided_at, decided_by) "
            "VALUES (?, ?, 'approved', datetime('now','localtime'), datetime('now','localtime'), ?)",
            (task_id, user_id, user_id),
        )
        conn.execute(
            "INSERT INTO task_members (task_id, user_id, status, updated_at) "
            "VALUES (?, ?, 'submitted', datetime('now','localtime'))",
            (task_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()
    return task_id


def test_historical_self_verification_is_rejected(ctx: _Ctx) -> None:
    """历史自验收数据（publisher == assignee）不得被放行，且不得加分。"""
    teacher_id = ctx.ids["teacher01"]
    task_id = _insert_historical_self_assignment("复审回归 历史自验收任务", teacher_id)

    _err(
        ctx.client,
        "POST",
        f"/api/tasks/{task_id}/verify",
        code=ERR_FORBIDDEN,
        token=ctx.teacher,
        body={"pass": True, "user_id": teacher_id},
        label="历史自验收 4030",
    )

    detail = _task(ctx.client, task_id, ctx.teacher)
    member = _member(detail, teacher_id)
    assert member is not None and member.get("status") == "submitted", f"自验收被拒后成员仍 submitted（实际 {member}）"
    assert detail.get("status") == "submitted", f"自验收被拒后任务状态不变（实际 {detail.get('status')}）"
    positive_logs = [log for log in _task_logs(ctx.client, ctx.teacher, task_id) if int(log.get("delta") or 0) > 0]
    assert positive_logs == [], f"自验收被拒不得产生正积分流水（实际 {positive_logs}）"


def test_cleared_deadline_stops_deadline_reminders(ctx: _Ctx) -> None:
    """PATCH deadline=null 后调度器不再产生截止相关提醒与逾期扣分。"""
    now = _now()
    task = _create_task(
        ctx.client,
        ctx.teacher,
        "复审回归 清空截止时间任务",
        quota=2,
        credit_reward=10,
        deadline=_fmt(now + timedelta(days=2)),
        reminder_rule={"days_before": 3, "day_of": True, "on_overdue": True},
    )
    task_id = task["id"]
    _apply_and_approve(ctx.client, ctx.teacher, ctx.s1, task_id)

    cleared = _ok(ctx.client, "PATCH", f"/api/tasks/{task_id}", token=ctx.teacher, body={"deadline": None}, label="清空截止时间")
    assert cleared.get("deadline") is None, f"PATCH deadline=null 后截止时间为空（实际 {cleared.get('deadline')!r}）"
    assert _task(ctx.client, task_id, ctx.teacher).get("deadline") is None, "清空后任务详情 deadline 为 null"

    reminder_scheduler.scan_and_remind(now=now)

    assert _reminders(ctx.client, ctx.s1, task_id) == [], "无截止时间时不得产生截止相关催办"
    assert _penalties(ctx.client, ctx.s1, task_id) == [], "无截止时间时不得逾期扣分"