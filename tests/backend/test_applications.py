#!/usr/bin/env python
"""T8-③ 报名审批矩阵（契约 `C-APPLY@1` / `C-DATA@2`，覆盖 R16-AC1~AC16）。

第二轮迭代的核心回归：**「quota=8 时第 2/3 人也能报名」**（第一轮 D1 单负责人模型的
8 名额 bug）。本脚本只通过 HTTP 业务接口驱动，唯一的 SQL 直写用于构造 legacy 数据
（`assignee_id` 非空但无任何报名行，验证不做数据迁移的兼容读取）。

覆盖矩阵（R16-ACx → 用例）：
- AC1  报名落 pending + 通知发布者/学生
- AC2  quota=8 已有 1 名 approved 时第 2、3 人仍可报名（**8 名额 bug 直接回归**）
- AC3  满额 4090「名额已满」（quota=2 任务）
- AC4  同人重复报名 4090「已报名」；rejected / cancelled 允许重新报名
- AC5  pending 撤回成功（cancelled + 发布者通知）
- AC6  approved 撤回 4090（发布者已确认不可撤回）
- AC7  审批通过：approved / decided_at / decided_by / assignee_id / published→claimed / 通知
- AC8  拒绝无 reason 4001；带 reason → rejected + 原因保存 + 通知
- AC9  验收对**每名 approved 成员**各 +credit_reward，幂等（重复 verify 4090 + 不新增流水）
- AC10 两名 approved 各 progress/submit；非成员 4030
- AC11 两名 approved 各签到；重复 4090；第三人 4030
- AC12 TaskOut 4 个派生字段
- AC13 legacy（assignee_id 无报名行）approved_count=1 / 可签到
- AC14 claim 是 apply 的别名（返回 ApplyOut）
- AC15 is_claimable 满额置灰依据
- AC16 非发布者查看/审批 4030

运行前提：``T10_BASE_URL``（8021）、``T10_DB_PATH``（临时库，由 run_all.sh 导出）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.getenv("T10_BASE_URL", "http://127.0.0.1:8021").rstrip("/")
DB_PATH = (os.getenv("T10_DB_PATH") or "").strip()
BACKEND_DIR = (
    os.getenv("T10_BACKEND_DIR") or str(Path(__file__).resolve().parents[2] / "backend")
).strip()

#: 阶段 2 测试账号统一密码；临时库由本脚本直写 ``scrypt`` 哈希（`C-HASH@1`）。
PASSWORD = "TestPass123!"

#: 临时库没有阶段 1 的演示账号，启动时按原有展示名 / 角色准备可登录账号。
SEED_USERS: dict[str, tuple[str, str]] = {
    "teacher01": ("王老师", "publisher"),
    "student01": ("李同学", "student"),
    "student02": ("张同学", "student"),
    "student03": ("陈同学", "student"),
}

#: 阶段 2 的组织可见性：无组织任务仅对发布者/负责人可见，脚本任务统一归入演示组织。
DEMO_ORG_NAME = "演示校区志愿队"
DEMO_ORG_SLUG = "demo-campus"
DEFAULT_ORG_ID: int | None = None

TITLE_QUOTA8 = "T8 R16-AC2 八名额多人报名任务"
TITLE_QUOTA2 = "T8 R16-AC3 满额拦截任务"
TITLE_WITHDRAW = "T8 R16-AC5/AC8 撤回与拒绝任务"
TITLE_MULTI = "T8 R16-AC9/AC10/AC11 多成员积分与签到任务"
TITLE_SELF = "T8 R16-AC1 发布者自报名任务"
TITLE_DEP_PARENT = "T8 R16-AC1 依赖父任务"
TITLE_DEP_DONE = "T8 R16-AC1 依赖前置任务"
TITLE_DEP_BLOCKED = "T8 R16-AC1 依赖被阻塞任务"
TITLE_CANCELLED = "T8 R16-AC1 已取消任务"
TITLE_CLAIM_ALIAS = "T8 R16-AC14 claim 别名任务"
TITLE_LEGACY = "T8 R16-AC13 legacy 兼容任务"

#: 禁止出现在字段值中的建议语（R13-AC5 同源红线，本脚本仅用于 TaskOut 文本字段）
TRACE_MARKERS = ("AI建议", "改为", "用户：")

_passed = 0


def expect(condition: bool, message: str) -> bool:
    """断言包装：通过打印 ``PASS`` 并计数，失败打印 ``FAIL`` 后立即退出 1。"""
    global _passed
    if condition:
        _passed += 1
        print(f"PASS: {message}")
        return True
    print(f"FAIL: {message}")
    raise SystemExit(1)


# --------------------------------------------------------------------------- #
# HTTP 工具（仅标准库；中文 body 用 urllib + UTF-8，避免 curl 编码问题）
# --------------------------------------------------------------------------- #
def ensure_seed_users() -> int:
    """直写临时库准备可登录账号与演示组织，返回组织 ID。

    阶段 2 登录改为账号密码，且 ``org_id IS NULL`` 的任务只对发布者/负责人可见；
    因此脚本账号必须同属一个组织，任务才能被成员看到并报名。
    """
    expect(bool(DB_PATH) and os.path.exists(DB_PATH), f"被测数据库存在：{DB_PATH}")
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)
    try:
        from app.security import hash_password  # noqa: PLC0415 - 依赖后端工程路径
    except Exception as exc:  # noqa: BLE001 - 依赖缺失时给出可执行原因
        print(f"FAIL: 无法导入 app.security（{type(exc).__name__}: {exc}）；BACKEND_DIR={BACKEND_DIR}")
        raise SystemExit(1)

    password_hash = hash_password(PASSWORD)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        for username, (display_name, role) in SEED_USERS.items():
            row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO users "
                    "(username, display_name, role, credits, password_hash, status, platform_admin) "
                    "VALUES (?, ?, ?, 0, ?, 'active', 0)",
                    (username, display_name, role, password_hash),
                )
            else:
                conn.execute(
                    "UPDATE users SET display_name = ?, role = ?, password_hash = ?, "
                    "status = 'active' WHERE username = ?",
                    (display_name, role, password_hash, username),
                )

        org_row = conn.execute(
            "SELECT id FROM organizations WHERE slug = ?", (DEMO_ORG_SLUG,)
        ).fetchone()
        if org_row is None:
            org_id = int(
                conn.execute(
                    "INSERT INTO organizations (name, slug, status, created_at) "
                    "VALUES (?, ?, 'active', datetime('now','localtime'))",
                    (DEMO_ORG_NAME, DEMO_ORG_SLUG),
                ).lastrowid
            )
        else:
            org_id = int(org_row[0])

        for username in SEED_USERS:
            user_row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            role = "admin" if username == "teacher01" else "member"
            existing = conn.execute(
                "SELECT id FROM org_members WHERE org_id = ? AND user_id = ?",
                (org_id, int(user_row[0])),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO org_members (org_id, user_id, role, title, status, created_at) "
                    "VALUES (?, ?, ?, NULL, 'active', datetime('now','localtime'))",
                    (org_id, int(user_row[0]), role),
                )
            else:
                conn.execute(
                    "UPDATE org_members SET role = ?, status = 'active' WHERE id = ?",
                    (role, int(existing[0])),
                )
        conn.commit()
    finally:
        conn.close()
    print(f"INFO: 已准备测试账号 {sorted(SEED_USERS)}（密码 {PASSWORD}）与组织 {DEMO_ORG_SLUG}(id={org_id})")
    return org_id


def _session_headers(token: dict[str, str] | None, method: str) -> dict[str, str]:
    """Cookie 会话 + CSRF 双提交头（GET/HEAD/OPTIONS 不需要 CSRF）。"""
    if not token:
        return {}
    headers = {"Cookie": f"cta_session={token['session']}; cta_csrf={token['csrf']}"}
    if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        headers["X-CSRF-Token"] = token["csrf"]
    return headers


def _cookies_from_response(headers) -> dict[str, str]:
    jar: dict[str, str] = {}
    for raw in headers.get_all("Set-Cookie") or []:
        name, _, value = raw.split(";", 1)[0].partition("=")
        jar[name.strip()] = value.strip()
    return jar


def http_json(
    method: str,
    path: str,
    body: object | None = None,
    token: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict, object]:
    # 阶段 2 可见性：新任务统一归属演示组织，成员才能在列表/详情中看到并报名。
    if (
        DEFAULT_ORG_ID is not None
        and method.upper() == "POST"
        and path == "/api/tasks"
        and isinstance(body, dict)
        and "org_id" not in body
    ):
        body = {**body, "org_id": DEFAULT_ORG_ID}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE_URL + path, data=payload, method=method)
    if payload is not None:
        request.add_header("Content-Type", "application/json; charset=utf-8")
    for name, value in _session_headers(token, method).items():
        request.add_header(name, value)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8")), response.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw), exc.headers
        except json.JSONDecodeError:
            return exc.code, {"code": None, "msg": raw[:200], "data": None}, exc.headers
    except urllib.error.URLError as exc:
        print(f"FAIL: 无法连接后端 {BASE_URL}（{exc}）；请先执行 bash tests/backend/run_all.sh")
        raise SystemExit(1)


def api_ok(method: str, path: str, body: object | None = None, token: dict[str, str] | None = None, label: str = "") -> dict:
    status, payload, _ = http_json(method, path, body, token)
    code = payload.get("code")
    expect(
        status == 200 and code == 0,
        f"{label}：期望 HTTP 200 + code=0，实际 HTTP {status} + code={code}（msg={payload.get('msg')}）",
    )
    data = payload.get("data")
    expect(isinstance(data, dict), f"{label}：data 为对象（实际 {type(data).__name__}）")
    return data


def api_err(
    method: str,
    path: str,
    code: int,
    body: object | None = None,
    token: dict[str, str] | None = None,
    expected_status: int | None = None,
    label: str = "",
) -> dict:
    status, payload, _ = http_json(method, path, body, token)
    expect(
        payload.get("code") == code,
        f"{label}：期望 code={code}，实际 HTTP {status} + code={payload.get('code')}（msg={payload.get('msg')}）",
    )
    # 阶段 2 迁移期口径：认证失败固定 401；越权由 C-AUTHZ 返回 403，
    # 旧业务校验（如报名列表仅发布者）仍为 200 —— 两者都接受，但 code 必须一致。
    if expected_status is None:
        if code == 4010:
            expected_status = 401
        elif code in (4030, 4040):
            expect(status in (200, 403, 404), f"{label}：越权/不存在响应应为 HTTP 200/403/404，实际 HTTP {status}")
            return payload
        else:
            expected_status = 200
    expect(status == expected_status, f"{label}：期望 HTTP {expected_status}，实际 HTTP {status}")
    return payload


# --------------------------------------------------------------------------- #
# 业务辅助
# --------------------------------------------------------------------------- #
def login(username: str) -> tuple[dict[str, str], dict]:
    """账号密码登录，返回 ``(Cookie/CSRF 凭据, user)``；不再使用 Bearer token。"""
    status, payload, headers = http_json(
        "POST", "/api/auth/login", {"username": username, "password": PASSWORD}
    )
    expect(
        status == 200 and payload.get("code") == 0,
        f"登录 {username}：期望 HTTP 200 + code=0，实际 HTTP {status} + code={payload.get('code')}（msg={payload.get('msg')}）",
    )
    data = payload.get("data") or {}
    cookies = _cookies_from_response(headers)
    expect(
        "cta_session" in cookies and "cta_csrf" in cookies,
        f"{username} 登录下发 cta_session/cta_csrf（实际 {sorted(cookies)}）",
    )
    user = data.get("user")
    expect(isinstance(user, dict), f"{username} 返回 user 对象")
    return {"session": cookies["cta_session"], "csrf": cookies["cta_csrf"]}, user


def create_task(token: str, body: dict, label: str) -> dict:
    data = api_ok("POST", "/api/tasks", body, token=token, label=label)
    expect(isinstance(data.get("id"), int) and data["id"] > 0, f"{label}：返回 int id")
    return data


def task_detail(task_id: int, token: str, label: str) -> dict:
    return api_ok("GET", f"/api/tasks/{task_id}", token=token, label=label)


def apply_task(token: str, task_id: int, label: str) -> dict:
    data = api_ok("POST", f"/api/tasks/{task_id}/apply", token=token, label=label)
    application = data.get("application")
    expect(isinstance(application, dict), f"{label}：返回 application 对象")
    expect(application.get("status") == "pending", f"{label}：报名状态 pending（实际 {application.get('status')}）")
    expect(isinstance(application.get("id"), int), f"{label}：返回 int application.id")
    expect(isinstance(data.get("task"), dict), f"{label}：返回最新 task 对象")
    return data


def decide(token: str, application_id: int, approve: bool, label: str, reason: str | None = None) -> dict:
    body: dict[str, object] = {"approve": approve}
    if reason is not None:
        body["reason"] = reason
    return api_ok("POST", f"/api/applications/{application_id}/decide", body, token=token, label=label)


def list_applications(token: str, task_id: int, label: str) -> list[dict]:
    data = api_ok("GET", f"/api/tasks/{task_id}/applications", token=token, label=label)
    items = data.get("items")
    expect(isinstance(items, list), f"{label}：items 为数组")
    return items


def my_applications(token: str, label: str) -> list[dict]:
    data = api_ok("GET", "/api/applications/me", token=token, label=label)
    items = data.get("items")
    expect(isinstance(items, list), f"{label}：items 为数组")
    return items


def credits_me(token: str, label: str) -> dict:
    data = api_ok("GET", "/api/credits/me", token=token, label=label)
    expect(isinstance(data.get("credits"), int), f"{label}：credits 为整数（实际 {data.get('credits')!r}）")
    return data


def notifications(token: str, label: str) -> list[dict]:
    data = api_ok("GET", "/api/notifications?limit=200", token=token, label=label)
    items = data.get("items")
    expect(isinstance(items, list), f"{label}：items 为数组")
    return items


def task_logs(credits: dict, task_id: int) -> list[dict]:
    return [log for log in credits.get("logs") or [] if log.get("task_id") == task_id]


def insert_legacy_task(publisher_id: int, assignee_id: int, title: str) -> int:
    """SQL 直写一条「assignee_id 非空但无任何报名行」的 legacy 任务（唯一允许的直写）。"""
    expect(bool(DB_PATH) and os.path.exists(DB_PATH), f"被测数据库存在：{DB_PATH}")
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.execute(
            "INSERT INTO tasks (title, status, publisher_id, assignee_id, created_at) "
            "VALUES (?, 'claimed', ?, ?, datetime('now','localtime'))",
            (title, publisher_id, assignee_id),
        )
        conn.commit()
        task_id = cursor.lastrowid
    finally:
        conn.close()
    expect(isinstance(task_id, int) and task_id > 0, f"legacy 任务插入成功（id={task_id}）")
    return int(task_id)


# --------------------------------------------------------------------------- #
# R16-AC2：quota=8 多人报名（8 名额 bug 直接回归）
# --------------------------------------------------------------------------- #
def case_quota_eight(
    teacher: str, s1: str, s2: str, s3: str, s1_id: int, s2_id: int, s3_id: int
) -> int:
    task = create_task(
        teacher,
        {"title": TITLE_QUOTA8, "description": "quota=8 多人报名回归", "quota": 8, "credit_reward": 20},
        "发布 quota=8 任务",
    )
    task_id = task["id"]
    expect(task.get("quota") == 8, "quota=8 回显")
    expect(task.get("applied_count") == 0 and task.get("approved_count") == 0, "新建任务计数为 0")

    first = apply_task(s1, task_id, "student01 报名（第 1 人）")
    expect(first["task"].get("applied_count") == 1, f"第 1 人报名后 applied_count=1（实际 {first['task'].get('applied_count')}）")
    expect(first["task"].get("approved_count") == 0, "第 1 人报名后 approved_count=0")

    # ★ 8 名额 bug 的直接回归：第 2 人（quota=8）必须可以报名
    second = apply_task(s2, task_id, "student02 报名（第 2 人，8 名额 bug 回归）")
    expect(second["application"].get("user_name") == "张同学", f"第 2 人 user_name=张同学（实际 {second['application'].get('user_name')}）")
    expect(second["task"].get("applied_count") == 2, f"第 2 人报名后 applied_count=2（实际 {second['task'].get('applied_count')}）")
    expect(second["task"].get("status") == "published", "第 2 人报名后任务仍 published（待审批）")

    items = list_applications(teacher, task_id, "发布者查看报名列表（3 条）")
    expect(len(items) == 2, f"报名列表 2 条（第 1/2 人，实际 {len(items)}）")
    expect([i.get("status") for i in items] == ["pending", "pending"], f"两条均为 pending（实际 {[i.get('status') for i in items]}）")
    expect([i.get("user_name") for i in items] == ["李同学", "张同学"], f"按报名先后返回（实际 {[i.get('user_name') for i in items]}）")
    api_err("GET", f"/api/tasks/{task_id}/applications", 4030, token=s1, label="非发布者查看报名列表 4030")

    first_approved = decide(teacher, first["application"]["id"], True, "通过第 1 人")
    expect(first_approved["task"].get("approved_count") == 1, "通过第 1 人后 approved_count=1")
    expect(first_approved["task"].get("status") == "claimed", "通过第 1 人后任务 claimed")
    expect(first_approved["task"].get("assignee_id") == s1_id, f"assignee_id 为首位成员（实际 {first_approved['task'].get('assignee_id')}）")
    expect(first_approved["task"].get("assignee_names") == ["李同学"], f"assignee_names=[李同学]（实际 {first_approved['task'].get('assignee_names')}）")
    expect(first_approved["application"].get("decided_at") is not None, "通过后写 decided_at")
    expect(first_approved["application"].get("status") == "approved", "通过后 application=approved")

    # ★ 已有 1 名 approved 时，第 3 人仍可报名（quota=8 未满）
    third = apply_task(s3, task_id, "student03 报名（第 3 人，已有 1 名 approved）")
    expect(third["task"].get("approved_count") == 1, "第 3 人报名时 approved_count 仍为 1")
    expect(third["task"].get("applied_count") == 2, f"第 3 人报名后 applied_count=2（实际 {third['task'].get('applied_count')}）")

    second_approved = decide(teacher, second["application"]["id"], True, "通过第 2 人")
    expect(second_approved["task"].get("approved_count") == 2, f"通过第 2 人后 approved_count=2（实际 {second_approved['task'].get('approved_count')}）")
    expect(second_approved["task"].get("assignee_names") == ["李同学", "张同学"], f"assignee_names 含两人（实际 {second_approved['task'].get('assignee_names')}）")
    expect(second_approved["task"].get("assignee_id") == s1_id, "assignee_id 仍为第一位 approved（不覆盖）")

    third_approved = decide(teacher, third["application"]["id"], True, "通过第 3 人")
    expect(third_approved["task"].get("approved_count") == 3, f"通过第 3 人后 approved_count=3（实际 {third_approved['task'].get('approved_count')}）")
    expect(third_approved["task"].get("assignee_names") == ["李同学", "张同学", "陈同学"], f"assignee_names 含三人（实际 {third_approved['task'].get('assignee_names')}）")

    api_err("POST", f"/api/applications/{first['application']['id']}/decide", 4090, {"approve": True}, token=teacher, label="重复审批已处理报名 4090")
    api_err("POST", f"/api/tasks/{task_id}/apply", 4090, token=s1, label="同人重复报名 4090")
    api_err("POST", f"/api/applications/{third['application']['id']}/decide", 4030, {"approve": True}, token=s2, label="非发布者审批 4030")

    # TaskOut 派生字段（AC12）：成员视角状态 / is_claimable
    s1_view = task_detail(task_id, s1, "student01 视角详情")
    expect(s1_view.get("my_application_status") == "approved", f"student01 my_application_status=approved（实际 {s1_view.get('my_application_status')}）")
    expect(s1_view.get("is_claimable") is False, "已 approved 成员不可再报名")
    s3_view = task_detail(task_id, s3, "student03 视角详情")
    expect(s3_view.get("my_application_status") == "approved", "student03 也已 approved")
    expect(s3_view.get("approved_count") == 3 and s3_view.get("applied_count") == 0, "详情派生计数字段正确")

    publisher_view = task_detail(task_id, teacher, "发布者视角详情")
    expect(publisher_view.get("assignee_name") == "李同学", f"assignee_name 为首位成员（实际 {publisher_view.get('assignee_name')}）")
    expect(publisher_view.get("my_application_status") is None, "发布者无报名状态（null）")

    # AC15：满额前 is_claimable 依据 —— quota=8 尚有余量，第四人（新登录用户）可报名由列表推导
    return task_id


# --------------------------------------------------------------------------- #
# R16-AC3：满额 4090（quota=2 与 quota=1 二次校验）
# --------------------------------------------------------------------------- #
def case_quota_full(teacher: str, s1: str, s2: str, s3: str) -> None:
    task = create_task(teacher, {"title": TITLE_QUOTA2 + "（quota=2）", "quota": 2}, "发布 quota=2 任务")
    task_id = task["id"]
    a1 = apply_task(s1, task_id, "quota=2 第 1 人报名")
    a2 = apply_task(s2, task_id, "quota=2 第 2 人报名")
    decide(teacher, a1["application"]["id"], True, "quota=2 通过第 1 人")
    decide(teacher, a2["application"]["id"], True, "quota=2 通过第 2 人")

    full = api_err("POST", f"/api/tasks/{task_id}/apply", 4090, token=s3, label="满额报名 4090")
    expect("名额已满" in (full.get("msg") or ""), f"4090 消息含「名额已满」（实际 {full.get('msg')}）")
    full_view = task_detail(task_id, s3, "满额任务详情")
    expect(full_view.get("approved_count") == 2 and full_view.get("quota") == 2, "满额任务 approved_count==quota")
    expect(full_view.get("is_claimable") is False, "满额时 is_claimable=false（前端置灰依据）")

    # 审批二次校验：quota=1 + 两条 pending，通过第 1 条后第 2 条必须 4090
    one = create_task(teacher, {"title": TITLE_QUOTA2 + "（quota=1）", "quota": 1}, "发布 quota=1 任务")
    b1 = apply_task(s1, one["id"], "quota=1 student01 报名")
    b2 = apply_task(s2, one["id"], "quota=1 student02 报名")
    decide(teacher, b1["application"]["id"], True, "quota=1 通过第 1 人")
    api_err("POST", f"/api/applications/{b2['application']['id']}/decide", 4090, {"approve": True}, token=teacher, label="quota=1 审批第 2 人 4090")
    b2_view = task_detail(one["id"], s2, "quota=1 第 2 人视角")
    expect(b2_view.get("my_application_status") == "pending", "超额审批失败后第 2 人仍为 pending（无脏写）")
    expect(b2_view.get("approved_count") == 1, "超额审批失败后 approved_count 仍为 1")


# --------------------------------------------------------------------------- #
# R16-AC4~AC8/AC16：撤回、拒绝、权限与错误码
# --------------------------------------------------------------------------- #
def case_withdraw_and_reject(teacher: str, s1: str, s2: str) -> None:
    task = create_task(teacher, {"title": TITLE_WITHDRAW, "quota": 5}, "发布撤回/拒绝用例任务")
    task_id = task["id"]

    first = apply_task(s1, task_id, "撤回用例：student01 报名")
    withdrawn = api_ok("POST", f"/api/tasks/{task_id}/apply/withdraw", token=s1, label="撤回 pending 报名")
    expect(withdrawn["application"].get("status") == "cancelled", f"撤回后状态 cancelled（实际 {withdrawn['application'].get('status')}）")
    expect(withdrawn["application"].get("decided_at") is None, "撤回后 decided_at 为 null")
    expect(withdrawn["task"].get("applied_count") == 0, "撤回后 applied_count=0")
    api_err("POST", f"/api/tasks/{task_id}/apply/withdraw", 4090, token=s1, label="重复撤回 4090")

    pub_notifies = notifications(teacher, "发布者通知（撤回后）")
    expect(any(n.get("task_id") == task_id and "撤回" in (n.get("title") or "") for n in pub_notifies), "撤回后发布者收到通知")

    reapplied = apply_task(s1, task_id, "cancelled 后重新报名")
    expect(reapplied["application"].get("id") == first["application"]["id"], "复用同一报名行（UNIQUE task+user）")
    expect(reapplied["task"].get("applied_count") == 1, "重新报名后 applied_count=1")
    expect(reapplied["application"].get("created_at") != "", "重新报名刷新 created_at")

    api_err("POST", f"/api/applications/{reapplied['application']['id']}/decide", 4001, {"approve": False}, token=teacher, label="拒绝无 reason 4001")
    api_err("POST", f"/api/applications/{reapplied['application']['id']}/decide", 4001, {"approve": False, "reason": "   "}, token=teacher, label="拒绝空白 reason 4001")

    rejected = decide(teacher, reapplied["application"]["id"], False, "拒绝报名（带原因）", reason="时间冲突")
    expect(rejected["application"].get("status") == "rejected", f"拒绝后状态 rejected（实际 {rejected['application'].get('status')}）")
    expect(rejected["application"].get("reason") == "时间冲突", f"拒绝原因落库（实际 {rejected['application'].get('reason')}）")
    expect(rejected["task"].get("applied_count") == 0, "拒绝后 applied_count=0")

    s1_notifies = notifications(s1, "学生通知（拒绝后）")
    expect(any(n.get("task_id") == task_id and "未通过" in (n.get("title") or "") for n in s1_notifies), "拒绝后学生收到「报名未通过」通知")
    expect(any("时间冲突" in (n.get("content") or "") for n in s1_notifies if n.get("task_id") == task_id), "通知内容含拒绝原因")

    again = apply_task(s1, task_id, "rejected 后重新报名")
    approved = decide(teacher, again["application"]["id"], True, "通过重新报名")
    expect(approved["application"].get("status") == "approved", "重新报名可通过")
    api_err("POST", f"/api/tasks/{task_id}/apply/withdraw", 4090, token=s1, label="已 approved 撤回 4090（AC6）")

    api_err("POST", "/api/applications/999999/decide", 4040, {"approve": True}, token=teacher, label="审批不存在报名 4040")
    api_err("POST", "/api/tasks/999999/apply", 4040, token=s1, label="报名不存在任务 4040")
    api_err("POST", "/api/tasks/999999/apply/withdraw", 4040, token=s1, label="撤回不存在任务 4040")


def case_apply_errors(teacher: str, s1: str) -> None:
    # AC1：发布者不能报名自己发布的任务
    own = create_task(teacher, {"title": TITLE_SELF, "quota": 3}, "发布自报名用例任务")
    api_err("POST", f"/api/tasks/{own['id']}/apply", 4030, token=teacher, label="发布者报名自己任务 4030")

    # 状态不允许：cancelled 任务
    cancelled = create_task(teacher, {"title": TITLE_CANCELLED}, "发布待取消任务")
    api_ok("PATCH", f"/api/tasks/{cancelled['id']}", {"status": "cancelled"}, token=teacher, label="取消任务")
    # 状态不允许：cancelled 任务。阶段 2 的 member 对 cancelled 任务不可见（C-AUTHZ@1），
    # 报名先被可见性拦为 4040（不泄露存在性），不再走到 4090。
    api_err(
        "POST", f"/api/tasks/{cancelled['id']}/apply", 4040, token=s1,
        label="cancelled 任务报名 4040（不可见）",
    )

    # 前置依赖未完成：4020 且消息含前置标题
    parent = create_task(teacher, {"title": TITLE_DEP_PARENT}, "发布依赖父任务")
    done = create_task(teacher, {"title": TITLE_DEP_DONE, "parent_id": parent["id"], "quota": 3}, "发布依赖前置任务")
    blocked = create_task(
        teacher,
        {"title": TITLE_DEP_BLOCKED, "parent_id": parent["id"], "depends_on": done["id"], "quota": 3},
        "发布被前置阻塞任务",
    )
    dep_error = api_err("POST", f"/api/tasks/{blocked['id']}/apply", 4020, token=s1, label="前置未完成报名 4020")
    expect(TITLE_DEP_DONE in (dep_error.get("msg") or ""), f"4020 消息含前置任务标题（实际 {dep_error.get('msg')}）")
    applied = apply_task(s1, done["id"], "无前置依赖的任务可报名")
    expect(applied["task"].get("status") == "published", "无依赖任务报名后仍 published")


# --------------------------------------------------------------------------- #
# R16-AC9/AC10/AC11：多成员加分幂等 + 多人签到
# --------------------------------------------------------------------------- #
def case_multi_member(
    teacher: str, s1: str, s2: str, s3: str, s1_id: int, s2_id: int
) -> None:
    task = create_task(
        teacher,
        {"title": TITLE_MULTI, "quota": 5, "credit_reward": 20},
        "发布多成员积分任务",
    )
    task_id = task["id"]
    base1 = credits_me(s1, "student01 积分基线")
    base2 = credits_me(s2, "student02 积分基线")
    c1, l1 = base1["credits"], len(base1.get("logs") or [])
    c2, l2 = base2["credits"], len(base2.get("logs") or [])

    a1 = apply_task(s1, task_id, "多成员：student01 报名")
    a2 = apply_task(s2, task_id, "多成员：student02 报名")
    decide(teacher, a1["application"]["id"], True, "多成员：通过 student01")
    decide(teacher, a2["application"]["id"], True, "多成员：通过 student02")

    # AC10：两名 approved 各 progress（claimed 首次推进 in_progress）
    p1 = api_ok("POST", f"/api/tasks/{task_id}/progress", {"content": "李同学进度：物料到位"}, token=s1, label="student01 进度")
    expect(p1.get("user_id") == s1_id, "进度记录 user_id 为 student01")
    after_p1 = task_detail(task_id, teacher, "首名成员进度后详情")
    expect(after_p1.get("status") == "in_progress", f"首次进度推进 in_progress（实际 {after_p1.get('status')}）")
    p2 = api_ok("POST", f"/api/tasks/{task_id}/progress", {"content": "张同学进度：海报完成"}, token=s2, label="student02 进度")
    expect(p2.get("user_id") == s2_id, "进度记录 user_id 为 student02")
    expect(len(after_p1.get("progress") or []) == 1, "progress_logs 首条落库")
    after_p2 = task_detail(task_id, teacher, "第二名成员进度后详情")
    expect(len(after_p2.get("progress") or []) == 2, f"progress_logs 两条（实际 {len(after_p2.get('progress') or [])}）")

    api_err("POST", f"/api/tasks/{task_id}/progress", 4030, {"content": "非成员进度"}, token=s3, label="非成员进度 4030")

    # AC10：两名 approved 各 submit（第二次为幂等成功）
    sub1 = api_ok("POST", f"/api/tasks/{task_id}/submit", token=s1, label="student01 提交")
    expect(sub1.get("status") == "submitted", f"student01 提交后 submitted（实际 {sub1.get('status')}）")
    sub2 = api_ok("POST", f"/api/tasks/{task_id}/submit", token=s2, label="student02 提交（幂等）")
    expect(sub2.get("status") == "submitted", f"student02 提交后仍 submitted（实际 {sub2.get('status')}）")
    api_err("POST", f"/api/tasks/{task_id}/submit", 4030, token=s3, label="非成员提交 4030")

    # AC9：验收 → 每名成员各 +20，credited_user_ids 两人
    verified = api_ok("POST", f"/api/tasks/{task_id}/verify", {"pass": True}, token=teacher, label="多成员验收通过")
    expect(verified.get("credit_delta") == 20, f"credit_delta=20（实际 {verified.get('credit_delta')}）")
    credited = verified.get("credited_user_ids") or []
    expect(sorted(credited) == sorted([s1_id, s2_id]), f"credited_user_ids 含两人（实际 {credited}）")
    expect(verified.get("task", {}).get("status") == "verified", "验收后任务 verified")

    after1 = credits_me(s1, "student01 验收后积分")
    after2 = credits_me(s2, "student02 验收后积分")
    expect(after1["credits"] == c1 + 20, f"student01 余额 +20（{c1} → {after1['credits']}）")
    expect(after2["credits"] == c2 + 20, f"student02 余额 +20（{c2} → {after2['credits']}）")
    logs1 = task_logs(after1, task_id)
    logs2 = task_logs(after2, task_id)
    expect(len(logs1) == 1 and logs1[0].get("delta") == 20, f"student01 本任务流水 1 条 +20（实际 {logs1}）")
    expect(len(logs2) == 1 and logs2[0].get("delta") == 20, f"student02 本任务流水 1 条 +20（实际 {logs2}）")
    expect("任务完成奖励" in (logs1[0].get("reason") or ""), "流水原因含「任务完成奖励」")

    # 幂等：重复验收 4090，流水不新增
    api_err("POST", f"/api/tasks/{task_id}/verify", 4090, {"pass": True}, token=teacher, label="重复验收 4090（已 verified）")
    repeat1 = credits_me(s1, "重复验收后 student01 积分")
    repeat2 = credits_me(s2, "重复验收后 student02 积分")
    expect(repeat1["credits"] == after1["credits"] and len(repeat1.get("logs") or []) == l1 + 1, "重复验收不新增 student01 流水")
    expect(repeat2["credits"] == after2["credits"] and len(repeat2.get("logs") or []) == l2 + 1, "重复验收不新增 student02 流水")
    expect(len(task_logs(repeat1, task_id)) == 1, "student01 本任务流水仍 1 条")

    # 通知：每名成员各收到「报名已通过」「验收通过」
    n1 = notifications(s1, "student01 通知（验收后）")
    n2 = notifications(s2, "student02 通知（验收后）")
    expect(any(n.get("task_id") == task_id and "报名已通过" in (n.get("title") or "") for n in n1), "student01 收到报名通过通知")
    expect(any(n.get("task_id") == task_id and "验收通过" in (n.get("title") or "") for n in n1), "student01 收到验收通过通知")
    expect(any(n.get("task_id") == task_id and "验收通过" in (n.get("title") or "") for n in n2), "student02 收到验收通过通知")

    # AC11：两人各签到；重复 4090；第三人 4030
    ck1 = api_ok("POST", "/api/checkin", {"task_id": task_id}, token=s1, label="student01 签到")
    ck2 = api_ok("POST", "/api/checkin", {"task_id": task_id}, token=s2, label="student02 签到")
    expect(ck1.get("user_id") == s1_id and ck2.get("user_id") == s2_id, "两人各记一条签到")
    api_err("POST", "/api/checkin", 4090, {"task_id": task_id}, token=s1, label="重复签到 4090")
    api_err("POST", "/api/checkin", 4030, {"task_id": task_id}, token=s3, label="非成员签到 4030")
    my_ck = api_ok("GET", "/api/checkin/me", token=s1, label="student01 签到列表")
    expect(any(i.get("task_id") == task_id for i in my_ck.get("items") or []), "checkin/me 含本任务签到")


def case_verify_reject(teacher: str, s1: str) -> None:
    """验收驳回：回 in_progress、不加分、成员收到 warning；可重新提交并验收通过。"""
    task = create_task(
        teacher, {"title": "T8 验收驳回后可重提任务", "quota": 1, "credit_reward": 15}, "发布驳回用例任务"
    )
    task_id = task["id"]
    applied = apply_task(s1, task_id, "驳回用例：报名")
    decide(teacher, applied["application"]["id"], True, "驳回用例：通过")
    api_ok("POST", f"/api/tasks/{task_id}/progress", {"content": "驳回用例进度"}, token=s1, label="驳回用例：进度")
    api_ok("POST", f"/api/tasks/{task_id}/submit", token=s1, label="驳回用例：提交")
    base = credits_me(s1, "驳回用例：积分基线")

    rejected = api_ok(
        "POST", f"/api/tasks/{task_id}/verify", {"pass": False, "reason": "物料缺失"}, token=teacher,
        label="验收驳回",
    )
    expect(rejected.get("task", {}).get("status") == "in_progress", f"驳回后回 in_progress（实际 {rejected.get('task', {}).get('status')}）")
    expect(rejected.get("credit_delta") == 0, f"驳回 credit_delta=0（实际 {rejected.get('credit_delta')}）")
    expect(rejected.get("credited_user_ids") == [], "驳回 credited_user_ids 为空")
    after = credits_me(s1, "驳回用例：驳回后积分")
    expect(after["credits"] == base["credits"], "驳回不扣分也不加分")
    warns = [n for n in notifications(s1, "驳回用例：学生通知") if n.get("task_id") == task_id and n.get("level") == "warning"]
    expect(len(warns) == 1, f"成员收到 1 条 warning（实际 {len(warns)}）")
    expect("物料缺失" in (warns[0].get("content") or ""), "驳回通知含原因")

    api_ok("POST", f"/api/tasks/{task_id}/submit", token=s1, label="驳回后重新提交")
    passed = api_ok("POST", f"/api/tasks/{task_id}/verify", {"pass": True}, token=teacher, label="驳回后验收通过")
    expect(passed.get("credit_delta") == 15, f"重新验收 +15（实际 {passed.get('credit_delta')}）")
    final = credits_me(s1, "驳回用例：最终积分")
    expect(final["credits"] == base["credits"] + 15, "重新验收仅加一次 15")


def case_legacy(teacher: str, s3: str, teacher_id: int, s3_id: int) -> None:
    """AC13：legacy（assignee_id 非空、无报名行）读取视角视为 approved，不做迁移。"""
    task_id = insert_legacy_task(teacher_id, s3_id, TITLE_LEGACY)
    teacher_view = task_detail(task_id, teacher, "legacy 任务（发布者视角）")
    expect(teacher_view.get("approved_count") == 1, f"legacy approved_count=1（实际 {teacher_view.get('approved_count')}）")
    expect(teacher_view.get("applied_count") == 0, "legacy applied_count=0")
    expect(teacher_view.get("assignee_names") == ["陈同学"], f"legacy assignee_names=[陈同学]（实际 {teacher_view.get('assignee_names')}）")
    expect(teacher_view.get("assignee_name") == "陈同学", "legacy assignee_name=陈同学")

    member_view = task_detail(task_id, s3, "legacy 任务（成员视角）")
    expect(member_view.get("my_application_status") == "approved", f"legacy my_application_status=approved（实际 {member_view.get('my_application_status')}）")
    expect(member_view.get("is_claimable") is False, "legacy 成员不可再报名")

    checkin = api_ok("POST", "/api/checkin", {"task_id": task_id}, token=s3, label="legacy 成员签到（回退生效）")
    expect(checkin.get("task_id") == task_id, "legacy 成员可签到")
    progress = api_ok("POST", f"/api/tasks/{task_id}/progress", {"content": "legacy 成员进度"}, token=s3, label="legacy 成员进度")
    expect(progress.get("task_id") == task_id, "legacy 成员可提交进度")


def case_scope_mine(s2: str, task_id: int) -> None:
    """T2 修复回归：scope=mine 必须包含第 2 名及以后的 approved 成员。"""
    data = api_ok("GET", "/api/tasks?scope=mine", token=s2, label="student02 scope=mine")
    items = data.get("items")
    expect(isinstance(items, list), "scope=mine 返回 items 数组")
    ids = [item.get("id") for item in items]
    expect(task_id in ids, f"第 2 名 approved 成员在 scope=mine 中可见（实际 ids={ids}）")
    target = next(item for item in items if item.get("id") == task_id)
    expect(target.get("my_application_status") == "approved", "scope=mine 命中项状态为 approved")


def case_my_applications(s1: str) -> None:
    """A5：我的报名返回 {items:[{application, task}]}，任务摘要非 null，倒序。"""
    items = my_applications(s1, "我的报名列表")
    expect(bool(items), "我的报名列表非空")
    expect(all(isinstance(item.get("application"), dict) for item in items), "每条含 application 对象")
    expect(all(isinstance(item.get("task"), dict) for item in items), "每条含 task 摘要（不返回 null）")
    times = [str((item.get("application") or {}).get("created_at") or "") for item in items]
    expect(times == sorted(times, reverse=True), f"按 created_at DESC 排序（实际 {times[:5]}）")
    titles = [(item.get("task") or {}).get("title") for item in items]
    expect(TITLE_QUOTA8 in titles, f"我的报名包含 quota=8 任务（实际 titles={titles[:8]}）")


def case_claim_alias(teacher: str, s1: str) -> None:
    """AC14：claim 保持可调用，语义等同 apply，返回 ApplyOut（不是裸 TaskOut）。"""
    task = create_task(teacher, {"title": TITLE_CLAIM_ALIAS, "quota": 2}, "发布 claim 别名任务")
    data = api_ok("POST", f"/api/tasks/{task['id']}/claim", token=s1, label="claim 别名")
    expect(isinstance(data.get("application"), dict), "claim 返回 application 对象")
    expect(data["application"].get("status") == "pending", f"claim 报名状态 pending（实际 {data['application'].get('status')}）")
    expect(isinstance(data.get("task"), dict), "claim 返回 task 对象")
    expect("status" not in data, "claim 响应顶层无 status（不是裸 TaskOut）")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    global DEFAULT_ORG_ID
    DEFAULT_ORG_ID = ensure_seed_users()
    teacher_token, teacher = login("teacher01")
    expect(teacher.get("role") == "publisher", f"teacher01 角色 publisher（实际 {teacher.get('role')}）")
    s1, s1_user = login("student01")
    s2, s2_user = login("student02")
    s3, s3_user = login("student03")
    s1_id, s2_id, s3_id = s1_user.get("id"), s2_user.get("id"), s3_user.get("id")
    expect(len({s1_id, s2_id, s3_id}) == 3, "三个学生账号互相独立")
    expect(s3_user.get("display_name") == "陈同学", f"student03 展示名 陈同学（实际 {s3_user.get('display_name')}）")

    # TabOut 文本字段红线（与 R13-AC5 同源）：任务文本不得混入追溯建议语
    quota8_id = case_quota_eight(teacher_token, s1, s2, s3, s1_id, s2_id, s3_id)
    view = task_detail(quota8_id, teacher_token, "quota=8 任务详情（红线）")
    for field in ("title", "description", "location", "start_time"):
        value = view.get(field)
        if isinstance(value, str):
            expect(not any(marker in value for marker in TRACE_MARKERS), f"TaskOut.{field} 不含追溯建议语（实际 {value!r}）")

    case_quota_full(teacher_token, s1, s2, s3)
    case_withdraw_and_reject(teacher_token, s1, s2)
    case_apply_errors(teacher_token, s1)
    case_multi_member(teacher_token, s1, s2, s3, s1_id, s2_id)
    case_verify_reject(teacher_token, s1)
    case_legacy(teacher_token, s3, int(teacher.get("id")), int(s3_id))
    case_scope_mine(s2, quota8_id)
    case_my_applications(s1)
    case_claim_alias(teacher_token, s1)

    print(f"---- test_applications.py 全部通过：{_passed} 项断言（R16-AC1~AC16）----")
    return 0


if __name__ == "__main__":
    sys.exit(main())
