#!/usr/bin/env python
"""T10-④ 真 SSE 推送 + 三级催办去重与逾期扣分（契约 `C-SSE@1` / `C-NOTIFY@1`）。

覆盖（plan T10 用例矩阵 ④）：
1. **真 SSE 推送**：``threading`` 起一条 ``urllib`` 长连接读
   ``/api/notifications/stream?token=``，另一线程（主线程）触发
   ``POST /api/tasks/{id}/verify``，断言 5 秒内收到 ``event: notify`` 且
   ``data`` 含 ``level`` 等 ``NotificationOut`` 字段；
2. **三级催办**：直接调用 ``scan_and_remind(now=...)`` 断言
   warning / urgent / overdue 三级计数（overdue 同时通知负责人与发布者，
   因此行数 ≠ 事件数）、逾期扣分仅 1 行（-10）、任务状态置 ``overdue``；
3. **二次扫描**：新增 0 条，通知与逾期流水均不增长（同一任务同一级别只提醒一次）。

隔离性说明：
- 本脚本通过 API 造 3 个催办任务（deadline 相对 ``now`` 计算，参数化，不等待真实时间）；
- 其余脚本创建的任务 ``deadline`` 均为空，因此不会落入扫描窗口；
- ``scan_and_remind`` 在**本进程内**调用，``DATABASE_PATH`` 与后端进程指向同一个
  临时库（由 ``run_all.sh`` 统一导出，禁止默认库）。

运行前提：``T10_BASE_URL`` / ``T10_DB_PATH`` / ``T10_BACKEND_DIR``（由 ``run_all.sh`` 导出）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE_URL = os.getenv("T10_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
DB_PATH = (os.getenv("T10_DB_PATH") or "").strip()
BACKEND_DIR = (os.getenv("T10_BACKEND_DIR") or str(Path(__file__).resolve().parents[2] / "backend")).strip()

# 必须在模块导入期就生效：ensure_seed_users() 会在 main() 之前导入 app.security
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

#: 阶段 2 测试账号统一密码；临时库由本脚本直写 ``scrypt`` 哈希（`C-HASH@1`）。
PASSWORD = "TestPass123!"

SEED_USERS: dict[str, tuple[str, str]] = {
    "teacher01": ("王老师", "publisher"),
    "student01": ("李同学", "student"),
}

#: 阶段 2 的组织可见性：无组织任务仅对发布者/负责人可见，脚本任务统一归入演示组织。
DEMO_ORG_NAME = "演示校区志愿队"
DEMO_ORG_SLUG = "demo-campus"
DEFAULT_ORG_ID: int | None = None

TITLE_SSE = "T10 SSE 推送验证任务"
TITLE_WARNING = "T10 催办预警任务（30 小时后截止）"
TITLE_URGENT = "T10 催办紧急任务（2 小时后截止）"
TITLE_OVERDUE = "T10 催办逾期任务（1 小时前已截止）"

SSE_WAIT_SECONDS = 5.0
DEADLINE_FORMAT = "%Y-%m-%d %H:%M:%S"

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
# HTTP 工具（仅标准库）
# --------------------------------------------------------------------------- #
def ensure_seed_users() -> int:
    """直写临时库准备可登录账号与演示组织，返回组织 ID。"""
    expect(bool(DB_PATH) and os.path.exists(DB_PATH), f"被测数据库存在：{DB_PATH}")
    try:
        from app.security import hash_password  # noqa: PLC0415 - 依赖后端工程路径
    except Exception as exc:  # noqa: BLE001
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
        conn.commit()
    finally:
        conn.close()
    org_conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        org_row = org_conn.execute(
            "SELECT id FROM organizations WHERE slug = ?", (DEMO_ORG_SLUG,)
        ).fetchone()
        if org_row is None:
            org_id = int(
                org_conn.execute(
                    "INSERT INTO organizations (name, slug, status, created_at) "
                    "VALUES (?, ?, 'active', datetime('now','localtime'))",
                    (DEMO_ORG_NAME, DEMO_ORG_SLUG),
                ).lastrowid
            )
        else:
            org_id = int(org_row[0])
        for username in SEED_USERS:
            user_row = org_conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            role = "admin" if username == "teacher01" else "member"
            existing = org_conn.execute(
                "SELECT id FROM org_members WHERE org_id = ? AND user_id = ?",
                (org_id, int(user_row[0])),
            ).fetchone()
            if existing is None:
                org_conn.execute(
                    "INSERT INTO org_members (org_id, user_id, role, title, status, created_at) "
                    "VALUES (?, ?, ?, NULL, 'active', datetime('now','localtime'))",
                    (org_id, int(user_row[0]), role),
                )
            else:
                org_conn.execute(
                    "UPDATE org_members SET role = ?, status = 'active' WHERE id = ?",
                    (role, int(existing[0])),
                )
        org_conn.commit()
    finally:
        org_conn.close()
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
    return {"session": cookies["cta_session"], "csrf": cookies["cta_csrf"]}, data["user"]


def notifications(token: str, label: str) -> list[dict]:
    data = api_ok("GET", "/api/notifications?limit=200", token=token, label=label)
    items = data.get("items")
    expect(isinstance(items, list), f"{label}：items 为数组")
    return items


def create_task(token: str, body: dict, label: str) -> dict:
    data = api_ok("POST", "/api/tasks", body, token=token, label=label)
    expect(isinstance(data.get("id"), int), f"{label}：返回 int id")
    return data


def apply_and_approve(teacher_token: str, student_token: str, task_id: int, label: str) -> dict:
    """P2：任务「成员化」必须走 apply → 发布者 approve（claim 不再直接写 assignee_id）。

    三级催办的 urgent / overdue 判定依赖 ``tasks.assignee_id``（P1 兼容字段仍由首位
    approved 写入），因此这里必须完成审批，否则催办不会被触发。
    """
    applied = api_ok("POST", f"/api/tasks/{task_id}/apply", token=student_token, label=f"{label}：报名")
    application = applied.get("application") or {}
    expect(application.get("status") == "pending", f"{label}：报名状态 pending（实际 {application.get('status')}）")
    expect(isinstance(application.get("id"), int), f"{label}：返回 application.id")
    approved = api_ok(
        "POST",
        f"/api/applications/{application['id']}/decide",
        {"approve": True},
        token=teacher_token,
        label=f"{label}：审批通过",
    )
    expect(approved.get("task", {}).get("status") == "claimed", f"{label}：审批后任务 claimed（实际 {approved.get('task', {}).get('status')}）")
    expect(approved.get("task", {}).get("assignee_id") is not None, f"{label}：审批后写入首位 assignee_id")
    return approved


# --------------------------------------------------------------------------- #
# ① 真 SSE 推送
# --------------------------------------------------------------------------- #
def sse_probe(url: str, headers: dict[str, str], result: dict, ready: threading.Event) -> None:
    """SSE 长连接读取线程：记录首帧，等待 ``event: notify`` 后立即返回。"""
    response = None
    try:
        request = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(request, timeout=SSE_WAIT_SECONDS + 1.0)
        result["status"] = response.status
        result["content_type"] = response.headers.get("Content-Type", "")

        event_name: str | None = None
        deadline = time.monotonic() + SSE_WAIT_SECONDS
        first_line = True
        while time.monotonic() < deadline:
            raw = response.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if first_line:
                result["first_line"] = line
                ready.set()
                first_line = False
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload_raw = line.split(":", 1)[1].strip()
                if event_name == "notify":
                    result["event"] = "notify"
                    try:
                        result["data"] = json.loads(payload_raw)
                    except json.JSONDecodeError:
                        result["data_raw"] = payload_raw
                    return
    except Exception as exc:  # 超时 / 连接中断：交给主线程断言
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:  # 关闭失败不影响断言结论
                pass


def verify_sse_push(teacher_token: str, student_token: str, student_id: int) -> None:
    """发布 → 认领 → 进度 → 提交 后用真 SSE 连接截获验收通知。"""
    task = create_task(teacher_token, {"title": TITLE_SSE, "description": "SSE 推送用例"}, label="发布 SSE 任务")
    task_id = task["id"]
    apply_and_approve(teacher_token, student_token, task_id, "SSE 任务")
    api_ok("POST", f"/api/tasks/{task_id}/progress", {"content": "SSE 用例进度"}, token=student_token, label="SSE 任务进度")
    api_ok("POST", f"/api/tasks/{task_id}/submit", token=student_token, label="SSE 任务提交")

    # 阶段 2：SSE 只接受 Cookie 会话，禁止 ``?token=`` 查询参数。
    url = f"{BASE_URL}/api/notifications/stream"
    sse_headers = {
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Cookie": f"cta_session={student_token['session']}; cta_csrf={student_token['csrf']}",
    }
    result: dict = {}
    ready = threading.Event()
    reader = threading.Thread(target=sse_probe, args=(url, sse_headers, result, ready), daemon=True, name="t10-sse-reader")
    reader.start()

    expect(
        ready.wait(SSE_WAIT_SECONDS + 5.0),
        f"SSE 连接建立并收到首帧（error={result.get('error')}）",
    )
    expect(result.get("status") == 200, f"SSE 响应 HTTP 200（实际 {result.get('status')}）")
    expect("text/event-stream" in (result.get("content_type") or ""), f"SSE Content-Type 为 text/event-stream（实际 {result.get('content_type')}）")
    expect(result.get("first_line") == ": ping", f"SSE 首帧为心跳注释行（实际 {result.get('first_line')!r}）")

    verified = api_ok("POST", f"/api/tasks/{task_id}/verify", {"pass": True}, token=teacher_token, label="SSE 任务验收（触发通知）")
    expect(verified.get("credit_delta") == 20, "SSE 验收加分成功（触发通知的前置条件）")

    reader.join(SSE_WAIT_SECONDS + 2.0)
    expect(not reader.is_alive(), "SSE 读取线程已结束（5 秒内收到事件或被超时中断）")
    expect(result.get("event") == "notify", f"5 秒内收到 event: notify（实际 {result.get('event')!r}，error={result.get('error')}）")

    payload = result.get("data") or {}
    expect(isinstance(payload, dict) and payload, f"notify data 为 JSON 对象（实际 {result.get('data') or result.get('data_raw')!r}）")
    expect(isinstance(payload.get("level"), str), f"notify data 含 level（实际 {payload.get('level')!r}）")
    expect(payload.get("level") in {"info", "warning", "urgent", "overdue"}, f"notify level 取值合法（实际 {payload.get('level')}）")
    expect(payload.get("user_id") == student_id, f"notify 推送给负责人（期望 {student_id}，实际 {payload.get('user_id')}）")
    expect(payload.get("task_id") == task_id, f"notify 关联任务 id 正确（期望 {task_id}，实际 {payload.get('task_id')}）")
    expect(isinstance(payload.get("title"), str) and payload["title"], f"notify 含标题（实际 {payload.get('title')!r}）")
    expect(isinstance(payload.get("is_read"), int), f"notify 含 is_read 字段（实际 {payload.get('is_read')!r}）")


# --------------------------------------------------------------------------- #
# ② 三级催办 + 去重 + 逾期扣分
# --------------------------------------------------------------------------- #
#: 催办级别（info 属业务通知，不计入催办计数）
REMINDER_LEVELS = frozenset({"warning", "urgent", "overdue"})


def count_by_task(notifies: list[dict], task_ids: set[int]) -> dict[tuple[int, str], int]:
    """按 ``(task_id, level)`` 汇总**催办**通知条数（忽略 claim/submit 产生的 info）。"""
    counter: dict[tuple[int, str], int] = {}
    for item in notifies:
        task_id = item.get("task_id")
        level = str(item.get("level"))
        if task_id not in task_ids or level not in REMINDER_LEVELS:
            continue
        key = (int(task_id), level)
        counter[key] = counter.get(key, 0) + 1
    return counter


def log_candidates(now: datetime) -> None:
    """打印扫描前的候选任务（便于失败时定位"额外命中"来自何处）。"""
    if not (DB_PATH and os.path.exists(DB_PATH)):
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT id, title, status, deadline FROM tasks "
            "WHERE status IN ('published','claimed','in_progress') AND deadline IS NOT NULL ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    print(f"INFO: now={now.strftime(DEADLINE_FORMAT)}，扫描候选任务 {len(rows)} 条：")
    for row in rows:
        print(f"INFO:   id={row[0]} status={row[2]} deadline={row[3]} title={row[1]}")


def verify_reminders(teacher_token: str, student_token: str) -> None:
    """造 3 个催办任务，直接调用 ``scan_and_remind`` 断言三级计数 / 去重 / 扣分。"""
    expect(os.path.isdir(BACKEND_DIR), f"后端目录存在：{BACKEND_DIR}")
    expect(bool(DB_PATH) and os.path.exists(DB_PATH), f"被测数据库存在：{DB_PATH}")

    now = datetime.now().replace(microsecond=0)
    warning_deadline = (now + timedelta(hours=30)).strftime(DEADLINE_FORMAT)
    urgent_deadline = (now + timedelta(hours=2)).strftime(DEADLINE_FORMAT)
    overdue_deadline = (now - timedelta(hours=1)).strftime(DEADLINE_FORMAT)

    # W：published + 30 小时后截止，days_before=2 ⇒ warning（接收人 = 发布者，因无负责人）
    warning_task = create_task(
        teacher_token,
        {
            "title": TITLE_WARNING,
            "deadline": warning_deadline,
            "reminder_rule": {"days_before": 2, "day_of": True, "on_overdue": True},
        },
        label="发布预警任务",
    )
    # U：claimed + 2 小时后截止 ⇒ urgent（接收人 = 负责人）
    urgent_task = create_task(
        teacher_token,
        {"title": TITLE_URGENT, "deadline": urgent_deadline},
        label="发布紧急任务",
    )
    apply_and_approve(teacher_token, student_token, urgent_task["id"], "紧急任务")

    # O：in_progress + 1 小时前截止 ⇒ overdue（通知负责人 + 发布者，扣分 -10）
    overdue_task = create_task(
        teacher_token,
        {"title": TITLE_OVERDUE, "deadline": overdue_deadline},
        label="发布逾期任务",
    )
    apply_and_approve(teacher_token, student_token, overdue_task["id"], "逾期任务")
    api_ok(
        "POST",
        f"/api/tasks/{overdue_task['id']}/progress",
        {"content": "逾期用例进度"},
        token=student_token,
        label="逾期任务进度（推进 in_progress）",
    )

    task_ids = {warning_task["id"], urgent_task["id"], overdue_task["id"]}
    baseline_credits = api_ok("GET", "/api/credits/me", token=student_token, label="扫描前积分基线")

    log_candidates(now)

    # 进程内调用（DATABASE_PATH 复用后端进程的临时库）
    os.environ["DATABASE_PATH"] = DB_PATH
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)
    try:
        from app.services import reminder_scheduler
    except Exception as exc:  # 依赖缺失时给出明确原因
        print(f"FAIL: 无法导入 app.services.reminder_scheduler（{type(exc).__name__}: {exc}）")
        raise SystemExit(1)

    created = reminder_scheduler.scan_and_remind(now=now)
    expect(isinstance(created, int), f"scan_and_remind 返回 int（实际 {type(created).__name__}）")
    expect(created == 4, f"首轮新增 4 条通知：warning 1 + urgent 1 + overdue 2（实际 {created}）")

    teacher_notifies = notifications(teacher_token, "发布者通知（首轮扫描后）")
    student_notifies = notifications(student_token, "负责人通知（首轮扫描后）")
    teacher_counter = count_by_task(teacher_notifies, task_ids)
    student_counter = count_by_task(student_notifies, task_ids)

    expect(
        teacher_counter.get((warning_task["id"], "warning")) == 1,
        f"warning 通知发布者 1 条（实际 {teacher_counter.get((warning_task['id'], 'warning'))}）",
    )
    expect(
        teacher_counter.get((overdue_task["id"], "overdue")) == 1,
        f"overdue 通知发布者 1 条（实际 {teacher_counter.get((overdue_task['id'], 'overdue'))}）",
    )
    expect(
        student_counter.get((urgent_task["id"], "urgent")) == 1,
        f"urgent 通知负责人 1 条（实际 {student_counter.get((urgent_task['id'], 'urgent'))}）",
    )
    expect(
        student_counter.get((overdue_task["id"], "overdue")) == 1,
        f"overdue 通知负责人 1 条（实际 {student_counter.get((overdue_task['id'], 'overdue'))}）",
    )
    total_rows = sum(teacher_counter.values()) + sum(student_counter.values())
    expect(total_rows == 4, f"本轮命中 3 任务共 4 条通知（overdue 双方各 1 条，实际 {total_rows}）")

    overdue_notifies = [
        item
        for item in teacher_notifies + student_notifies
        if item.get("task_id") == overdue_task["id"] and item.get("level") == "overdue"
    ]
    expect(len(overdue_notifies) == 2, f"overdue 通知共 2 条（负责人 + 发布者，实际 {len(overdue_notifies)}）")
    expect(all("已逾期" in (item.get("content") or "") for item in overdue_notifies), "overdue 文案含「已逾期」")
    expect(any("负责人" in (item.get("content") or "") for item in overdue_notifies), "overdue 文案含负责人名称")

    overdue_detail = api_ok("GET", f"/api/tasks/{overdue_task['id']}", token=teacher_token, label="逾期任务详情")
    expect(overdue_detail.get("status") == "overdue", f"逾期任务状态置 overdue（实际 {overdue_detail.get('status')}）")

    credits_after = api_ok("GET", "/api/credits/me", token=student_token, label="扫描后积分")
    expect(
        credits_after.get("credits") == baseline_credits.get("credits") - 10,
        f"逾期扣分 -10（基线 {baseline_credits.get('credits')} → 实际 {credits_after.get('credits')}）",
    )
    penalty_logs = [
        log
        for log in credits_after.get("logs") or []
        if log.get("task_id") == overdue_task["id"] and (log.get("reason") or "").startswith("逾期扣分")
    ]
    expect(len(penalty_logs) == 1, f"逾期扣分流水仅 1 行（实际 {len(penalty_logs)}）")
    expect(penalty_logs[0].get("delta") == -10, f"逾期流水 delta=-10（实际 {penalty_logs[0].get('delta')}）")

    # ---- 二次扫描：去重（0 新增）-----------------------------------------
    created_again = reminder_scheduler.scan_and_remind(now=now)
    expect(created_again == 0, f"二次扫描新增 0 条（实际 {created_again}）")

    teacher_again = count_by_task(notifications(teacher_token, "发布者通知（二次扫描后）"), task_ids)
    student_again = count_by_task(notifications(student_token, "负责人通知（二次扫描后）"), task_ids)
    expect(teacher_again == teacher_counter, "二次扫描后发布者通知数量不变")
    expect(student_again == student_counter, "二次扫描后负责人通知数量不变")

    credits_again = api_ok("GET", "/api/credits/me", token=student_token, label="二次扫描后积分")
    penalty_again = [
        log
        for log in credits_again.get("logs") or []
        if log.get("task_id") == overdue_task["id"] and (log.get("reason") or "").startswith("逾期扣分")
    ]
    expect(len(penalty_again) == 1, f"二次扫描后逾期流水仍 1 行（实际 {len(penalty_again)}）")
    expect(
        credits_again.get("credits") == credits_after.get("credits"),
        "二次扫描不重复扣分",
    )


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    global DEFAULT_ORG_ID
    DEFAULT_ORG_ID = ensure_seed_users()
    teacher_token, teacher = login("teacher01")
    teacher_id = teacher.get("id")
    student_token, student = login("student01")
    student_id = student.get("id")
    expect(teacher_id != student_id, "发布者与负责人为不同用户（保证 overdue 双通知可区分）")

    verify_sse_push(teacher_token, student_token, student_id)
    verify_reminders(teacher_token, student_token)

    print(f"---- test_sse_and_reminder.py 全部通过：{_passed} 项断言 ----")
    return 0


if __name__ == "__main__":
    sys.exit(main())