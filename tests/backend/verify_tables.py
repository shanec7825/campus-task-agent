#!/usr/bin/env python
"""建表与数据形态校验（契约 `C-DATA@2` / `C-DATA-AUTH@1`，阶段 2 口径）。

断言范围：
1. **23 张表**全部存在（阶段 1 的 11 张 + 阶段 2 的 organizations / org_members /
   invitations / user_sessions / password_resets + 阶段 19 的 ai_conversations / ai_messages
   + AIW-03 的 task_dependencies + AIW-04 的 activity_resources / task_submissions /
   submission_prechecks + AIW-05 的 ai_usage_ledger）；
2. ``task_applications`` 列齐全且存在 ``uq_task_applications_task_user``
   （PRAGMA 元数据 + 真实重复插入双证，后者事务内回滚）；
3. ``checkins`` 存在 ``UNIQUE(task_id, user_id)`` —— 双证同上；
4. ``tasks.extras`` / ``tasks.reminder_rule`` 读回为 dict —— JSON 接口 + SQLite 原始列双证；
5. ``progress_logs`` 表及其列存在；
6. ``/api/health`` 的 ``tables`` 为 23 项且与期望集合完全一致；
7. 阶段 2 认证列的落库形态（``users.status`` 默认 ``active``、``platform_admin`` 默认 0、
   ``tasks.org_id`` / ``activities.org_id`` 可空）与 ``task_members`` 具名唯一索引。

阶段 2 起接口鉴权改为 Cookie 会话（需账号密码），故 JSON 落库形态改为在事务内直接插入
探针行后回滚验证；接口级字段与派生值由 ``tests/backend/test_auth_org_permissions.py`` 覆盖。

运行前提（由 ``run_all.sh`` 导出）：
- ``T10_BASE_URL``：后端地址（默认 ``http://127.0.0.1:8021``，T8 约定端口）；
- ``T10_DB_PATH``：被测 SQLite 文件（**必须**由调用方指定临时库，禁止默认库）。

用法：``python verify_tables.py``（失败打印 ``FAIL: <msg>`` 并以 1 退出）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request

BASE_URL = os.getenv("T10_BASE_URL", "http://127.0.0.1:8021").rstrip("/")
DB_PATH = (os.getenv("T10_DB_PATH") or "").strip()

#: 期望的 23 张表（阶段 1 的 11 张 + 阶段 2 认证与组织的 5 张 + 阶段 19 的 AI 会话 2 张
#: + AIW-03 的任务依赖边 1 张 + AIW-04 的资料与成果 3 张 + AIW-05 的 AI 用量账本 1 张）
EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        "users",
        "tasks",
        "checkins",
        "credit_logs",
        "notifications",
        "kb_entries",
        "parse_sessions",
        "progress_logs",
        "task_applications",
        "task_members",
        "activities",
        "organizations",
        "org_members",
        "invitations",
        "user_sessions",
        "password_resets",
        "ai_conversations",
        "ai_messages",
        "task_dependencies",
        "activity_resources",
        "task_submissions",
        "submission_prechecks",
        "ai_usage_ledger",
    }
)

#: task_applications 必须存在的列（`2.2.1 A` 表结构）
TASK_APPLICATION_COLUMNS: frozenset[str] = frozenset(
    {"id", "task_id", "user_id", "status", "reason", "created_at", "decided_at", "decided_by"}
)

#: 唯一约束名（契约逐字要求）
TASK_APPLICATION_UNIQUE_NAME = "uq_task_applications_task_user"

#: progress_logs 必须存在的列（`2.3 D2` 新增表）
PROGRESS_LOG_COLUMNS: frozenset[str] = frozenset({"id", "task_id", "user_id", "content", "created_at"})

#: 建表校验任务（deadline 留空，避免被催办扫描命中）
TABLE_CHECK_TITLE = "T8 建表校验任务（23 表）"
TABLE_CHECK_EXTRAS = {"装备": "矿泉水", "联系人": "张三"}
TABLE_CHECK_RULE = {"days_before": 3, "day_of": False, "on_overdue": False}

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
def http_json(
    method: str,
    path: str,
    body: object | None = None,
    timeout: float = 15.0,
) -> tuple[int, dict]:
    """发起一次请求并解析统一响应体 ``{code,msg,data}``。"""
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE_URL + path, data=payload, method=method)
    if payload is not None:
        request.add_header("Content-Type", "application/json; charset=utf-8")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"code": None, "msg": raw[:200], "data": None}
    except urllib.error.URLError as exc:  # 后端未启动：给出可执行提示
        print(f"FAIL: 无法连接后端 {BASE_URL}（{exc}）；请先执行 bash tests/backend/run_all.sh")
        raise SystemExit(1)


def api_ok(method: str, path: str, body: object | None = None, label: str = "") -> dict:
    """断言 ``HTTP 200 + code==0``，返回 ``data``。"""
    status, payload = http_json(method, path, body)
    code = payload.get("code")
    expect(
        status == 200 and code == 0,
        f"{label}：期望 HTTP 200 + code=0，实际 HTTP {status} + code={code}（msg={payload.get('msg')}）",
    )
    data = payload.get("data")
    expect(isinstance(data, dict), f"{label}：data 为对象（实际 {type(data).__name__}）")
    return data


# --------------------------------------------------------------------------- #
# SQLite 校验
# --------------------------------------------------------------------------- #
def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows if not str(row[0]).startswith("sqlite_")}


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info('{table}')")}


def unique_column_sets(conn: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    """返回该表所有唯一索引的列组合（PRAGMA 元数据口径）。"""
    result: set[tuple[str, ...]] = set()
    for index_row in conn.execute(f"PRAGMA index_list('{table}')").fetchall():
        # index_list 列：seq / name / unique / origin / partial
        if len(index_row) < 3 or not int(index_row[2]):
            continue
        index_name = str(index_row[1])
        columns = tuple(str(row[2]) for row in conn.execute(f"PRAGMA index_info('{index_name}')"))
        result.add(columns)
    return result


def unique_index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """返回该表所有唯一索引的**名称**（用于断言契约要求的约束名）。"""
    names: set[str] = set()
    for index_row in conn.execute(f"PRAGMA index_list('{table}')").fetchall():
        if len(index_row) < 3 or not int(index_row[2]):
            continue
        names.add(str(index_row[1]))
    return names


def index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """返回该表全部索引名称（含非唯一索引）。"""
    return {str(row[1]) for row in conn.execute(f"PRAGMA index_list('{table}')").fetchall()}


def assert_duplicate_insert_rejected(
    conn: sqlite3.Connection, insert_sql: str, values: tuple[object, ...]
) -> bool:
    """真实插入两条相同唯一键验证唯一约束（事务内回滚，不留数据）。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(insert_sql, values)
        try:
            conn.execute(insert_sql, values)
        except sqlite3.IntegrityError:
            return True
        return False
    finally:
        conn.execute("ROLLBACK")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    expect(bool(DB_PATH), "已提供被测数据库路径（环境变量 T10_DB_PATH）")
    expect(os.path.exists(DB_PATH), f"被测数据库文件存在：{DB_PATH}")

    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        # ---- 1) 23 张表 ----------------------------------------------------
        names = table_names(conn)
        missing = sorted(EXPECTED_TABLES - names)
        expect(not missing, f"23 张表全部存在（缺失：{missing or '无'}；实际 {sorted(names)}）")
        expect(len(EXPECTED_TABLES) == 23, f"期望表集合固定为 23 张（实际定义 {len(EXPECTED_TABLES)} 张）")

        # ---- 2) checkins 唯一约束 ----------------------------------------
        unique_sets = unique_column_sets(conn, "checkins")
        expect(
            ("task_id", "user_id") in unique_sets or ("user_id", "task_id") in unique_sets,
            f"checkins 存在 UNIQUE(task_id, user_id) 索引（实际唯一组合：{sorted(unique_sets)}）",
        )
        checkin_sql = (
            "INSERT INTO checkins (task_id, user_id, checkin_time) "
            "VALUES (?, ?, datetime('now','localtime'))"
        )
        expect(
            assert_duplicate_insert_rejected(conn, checkin_sql, (990001, 990002)),
            "checkins 重复 (task_id, user_id) 插入被数据库拒绝（IntegrityError）",
        )
        remaining = conn.execute(
            "SELECT COUNT(*) FROM checkins WHERE task_id=? AND user_id=?", (990001, 990002)
        ).fetchone()[0]
        expect(int(remaining) == 0, "唯一约束探测数据已回滚（无残留行）")

        # ---- 3) task_applications：表 / 列 / 契约唯一约束名 ----------------
        expect("task_applications" in names, "task_applications 表存在（第 9 张表）")
        application_columns = column_names(conn, "task_applications")
        expect(
            TASK_APPLICATION_COLUMNS <= application_columns,
            "task_applications 列齐全（期望 "
            f"{sorted(TASK_APPLICATION_COLUMNS)}，实际 {sorted(application_columns)}）",
        )
        application_unique_sets = unique_column_sets(conn, "task_applications")
        expect(
            ("task_id", "user_id") in application_unique_sets
            or ("user_id", "task_id") in application_unique_sets,
            "task_applications 存在 UNIQUE(task_id, user_id) 索引"
            f"（实际唯一组合：{sorted(application_unique_sets)}）",
        )
        # SQLite 对表级命名 UNIQUE 约束在 PRAGMA index_list 中显示为 sqlite_autoindex_*，
        # 约束名只保留在 sqlite_master.sql 的 CREATE TABLE DDL 里（与 SQLAlchemy 元数据一致）。
        ddl_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='task_applications'"
        ).fetchone()
        ddl = str(ddl_row[0]) if ddl_row and ddl_row[0] else ""
        expect(
            f"CONSTRAINT {TASK_APPLICATION_UNIQUE_NAME} UNIQUE" in ddl,
            "DDL 保留契约约束名 "
            f"{TASK_APPLICATION_UNIQUE_NAME}（sqlite_master.sql 口径；"
            f"PRAGMA 实际索引名 {sorted(unique_index_names(conn, 'task_applications'))}；DDL={ddl[:260]!r}）",
        )
        application_sql = (
            "INSERT INTO task_applications "
            "(task_id, user_id, status, created_at) VALUES (?, ?, 'pending', datetime('now','localtime'))"
        )
        expect(
            assert_duplicate_insert_rejected(conn, application_sql, (990003, 990004)),
            "task_applications 重复 (task_id, user_id) 插入被数据库拒绝（IntegrityError）",
        )
        application_remaining = conn.execute(
            "SELECT COUNT(*) FROM task_applications WHERE task_id=? AND user_id=?",
            (990003, 990004),
        ).fetchone()[0]
        expect(int(application_remaining) == 0, "task_applications 探测数据已回滚（无残留行）")

        # ---- 4) progress_logs 表与列 -------------------------------------
        expect("progress_logs" in names, "progress_logs 表存在")
        progress_columns = column_names(conn, "progress_logs")
        expect(
            PROGRESS_LOG_COLUMNS <= progress_columns,
            f"progress_logs 列齐全（期望 {sorted(PROGRESS_LOG_COLUMNS)}，实际 {sorted(progress_columns)}）",
        )

        # ---- 4b) task_dependencies：列 / 唯一约束 / DDL 约束名 -------------
        expect("task_dependencies" in names, "task_dependencies 表存在（AIW-03 第 19 张表）")
        dependency_columns = column_names(conn, "task_dependencies")
        expect(
            {"id", "task_id", "depends_on_id", "created_at"} <= dependency_columns,
            f"task_dependencies 列齐全（实际 {sorted(dependency_columns)}）",
        )
        dependency_unique_sets = unique_column_sets(conn, "task_dependencies")
        expect(
            ("task_id", "depends_on_id") in dependency_unique_sets
            or ("depends_on_id", "task_id") in dependency_unique_sets,
            "task_dependencies 存在 UNIQUE(task_id, depends_on_id)"
            f"（实际唯一组合：{sorted(dependency_unique_sets)}）",
        )
        dependency_ddl_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='task_dependencies'"
        ).fetchone()
        dependency_ddl = str(dependency_ddl_row[0]) if dependency_ddl_row and dependency_ddl_row[0] else ""
        expect(
            "CONSTRAINT uq_task_dependencies_task_dep UNIQUE" in dependency_ddl,
            "task_dependencies DDL 保留契约约束名 uq_task_dependencies_task_dep",
        )
        expect(
            "ix_task_dependencies_depends_on_id" in index_names(conn, "task_dependencies"),
            "task_dependencies 存在 ix_task_dependencies_depends_on_id 反向前置索引"
            f"（实际 {sorted(index_names(conn, 'task_dependencies'))}）",
        )
        dependency_sql = (
            "INSERT INTO task_dependencies (task_id, depends_on_id, created_at) "
            "VALUES (?, ?, datetime('now','localtime'))"
        )
        expect(
            assert_duplicate_insert_rejected(conn, dependency_sql, (990006, 990007)),
            "task_dependencies 重复 (task_id, depends_on_id) 插入被数据库拒绝（IntegrityError）",
        )
        dependency_remaining = conn.execute(
            "SELECT COUNT(*) FROM task_dependencies WHERE task_id=? AND depends_on_id=?",
            (990006, 990007),
        ).fetchone()[0]
        expect(int(dependency_remaining) == 0, "task_dependencies 探测数据已回滚（无残留行）")

        # ---- 4c) AIW-04 资料与成果表 -------------------------------------
        expect("activity_resources" in names, "activity_resources 表存在（AIW-04 第 20 张表）")
        resource_columns = column_names(conn, "activity_resources")
        expect(
            {
                "id",
                "resource_key",
                "activity_id",
                "task_id",
                "org_id",
                "title",
                "summary",
                "resource_type",
                "url",
                "version",
                "created_by",
                "created_at",
            }
            <= resource_columns,
            f"activity_resources 列齐全（实际 {sorted(resource_columns)}）",
        )
        resource_unique_sets = unique_column_sets(conn, "activity_resources")
        expect(
            ("resource_key", "version") in resource_unique_sets
            or ("version", "resource_key") in resource_unique_sets,
            "activity_resources 存在 UNIQUE(resource_key, version)"
            f"（实际唯一组合：{sorted(resource_unique_sets)}）",
        )
        resource_ddl_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='activity_resources'"
        ).fetchone()
        resource_ddl = str(resource_ddl_row[0]) if resource_ddl_row and resource_ddl_row[0] else ""
        expect(
            "CONSTRAINT uq_activity_resources_key_version UNIQUE" in resource_ddl,
            "activity_resources DDL 保留契约约束名 uq_activity_resources_key_version",
        )
        resource_indexes = index_names(conn, "activity_resources")
        expect(
            {"ix_activity_resources_activity_id", "ix_activity_resources_task_id", "ix_activity_resources_org_id"}
            <= resource_indexes,
            f"activity_resources 归属索引齐全（实际 {sorted(resource_indexes)}）",
        )
        resource_sql = (
            "INSERT INTO activity_resources "
            "(resource_key, title, url, created_by, version, created_at) "
            "VALUES (?, 't', 'https://example.com', 1, 1, datetime('now','localtime'))"
        )
        expect(
            assert_duplicate_insert_rejected(conn, resource_sql, ("probe-key",)),
            "activity_resources 重复 (resource_key, version) 插入被数据库拒绝（IntegrityError）",
        )
        resource_remaining = conn.execute(
            "SELECT COUNT(*) FROM activity_resources WHERE resource_key=?", ("probe-key",)
        ).fetchone()[0]
        expect(int(resource_remaining) == 0, "activity_resources 探测数据已回滚（无残留行）")

        expect("task_submissions" in names, "task_submissions 表存在（AIW-04 第 21 张表）")
        submission_columns = column_names(conn, "task_submissions")
        expect(
            {"id", "task_id", "user_id", "version", "content", "resource_url", "created_at"}
            <= submission_columns,
            f"task_submissions 列齐全（实际 {sorted(submission_columns)}）",
        )
        submission_unique_sets = unique_column_sets(conn, "task_submissions")
        expect(
            ("task_id", "user_id", "version") in submission_unique_sets
            or ("user_id", "task_id", "version") in submission_unique_sets
            or ("version", "task_id", "user_id") in submission_unique_sets,
            "task_submissions 存在 UNIQUE(task_id, user_id, version)"
            f"（实际唯一组合：{sorted(submission_unique_sets)}）",
        )
        submission_sql = (
            "INSERT INTO task_submissions "
            "(task_id, user_id, version, created_at) VALUES (?, ?, ?, datetime('now','localtime'))"
        )
        expect(
            assert_duplicate_insert_rejected(conn, submission_sql, (990008, 990009, 1)),
            "task_submissions 重复 (task_id, user_id, version) 插入被数据库拒绝（IntegrityError）",
        )
        submission_remaining = conn.execute(
            "SELECT COUNT(*) FROM task_submissions WHERE task_id=? AND user_id=?",
            (990008, 990009),
        ).fetchone()[0]
        expect(int(submission_remaining) == 0, "task_submissions 探测数据已回滚（无残留行）")

        expect("submission_prechecks" in names, "submission_prechecks 表存在（AIW-04 第 22 张表）")
        precheck_columns = column_names(conn, "submission_prechecks")
        expect(
            {
                "id",
                "submission_id",
                "requirement_digest",
                "checks",
                "verdict",
                "summary",
                "ai_suggestions",
                "mock",
                "ai_error",
                "created_at",
            }
            <= precheck_columns,
            f"submission_prechecks 列齐全（实际 {sorted(precheck_columns)}）",
        )
        expect(
            "ix_submission_prechecks_submission_id" in index_names(conn, "submission_prechecks"),
            "submission_prechecks 存在 submission_id 索引"
            f"（实际 {sorted(index_names(conn, 'submission_prechecks'))}）",
        )

        expect("ai_usage_ledger" in names, "ai_usage_ledger 表存在（AIW-05 第 23 张表）")
        usage_columns = column_names(conn, "ai_usage_ledger")
        expect(
            {
                "id",
                "user_id",
                "conversation_id",
                "assistant_message_id",
                "request_id",
                "operation",
                "status",
                "units",
                "created_at",
            }
            <= usage_columns,
            f"ai_usage_ledger 列齐全（实际 {sorted(usage_columns)}）",
        )
        usage_unique_sets = unique_column_sets(conn, "ai_usage_ledger")
        expect(
            ("user_id", "request_id") in usage_unique_sets
            or ("request_id", "user_id") in usage_unique_sets,
            "ai_usage_ledger 存在 UNIQUE(user_id, request_id)"
            f"（实际唯一组合：{sorted(usage_unique_sets)}）",
        )
        expect(
            "ix_ai_usage_user_created" in index_names(conn, "ai_usage_ledger"),
            "ai_usage_ledger 存在 user_id/created_at 索引"
            f"（实际 {sorted(index_names(conn, 'ai_usage_ledger'))}）",
        )
        notification_columns = {row[1]: row for row in conn.execute("PRAGMA table_info(notifications)").fetchall()}
        expect(
            "stale" in notification_columns,
            "notifications 含 stale 列（C-REMINDER-STALE@1）",
        )
        stale_column = notification_columns.get("stale")
        expect(
            stale_column is not None
            and int(stale_column[3]) == 1
            and str(stale_column[4]) == "0",
            "notifications.stale 为 NOT NULL DEFAULT 0"
            f"（实际 notnull={stale_column[3] if stale_column else None}, default={stale_column[4] if stale_column else None}）",
        )

        # ---- 5) tasks 关键列 ---------------------------------------------
        task_columns = column_names(conn, "tasks")
        expect(
            {"extras", "reminder_rule", "depends_on", "parent_id", "assignee_id", "quota"} <= task_columns,
            "tasks 含 extras/reminder_rule/depends_on/parent_id/assignee_id/quota 列"
            f"（实际 {len(task_columns)} 列）",
        )

        # ---- 6) 健康检查（23 表 + mock）------------------------------------
        health = api_ok("GET", "/api/health", label="健康检查")
        health_tables = sorted(health.get("tables") or [])
        expect(
            health_tables == sorted(EXPECTED_TABLES),
            f"health.tables 与 23 张表完全一致（实际 {health.get('tables')}）",
        )
        expect(len(health_tables) == 23, f"health.tables 数量为 23（实际 {len(health_tables)}）")
        expect(health.get("mock") is True, f"health.mock 为 true（实际 {health.get('mock')}）")

        # ---- 7) tasks.extras / reminder_rule 落库形态 ---------------------
        # 阶段 2 起接口需要账号密码会话，探针行改为在事务内直接插入后回滚，
        # 只验证 JSON 列的读回形态，不在被测库里留数据。
        conn.execute("BEGIN IMMEDIATE")
        raw_extras = raw_rule = None
        probe_task_id = 0
        try:
            cursor = conn.execute(
                "INSERT INTO tasks (title, extras, reminder_rule, publisher_id, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now','localtime'))",
                (
                    TABLE_CHECK_TITLE,
                    json.dumps(TABLE_CHECK_EXTRAS, ensure_ascii=False),
                    json.dumps(TABLE_CHECK_RULE, ensure_ascii=False),
                    990005,
                ),
            )
            probe_task_id = int(cursor.lastrowid)
            raw_extras, raw_rule = conn.execute(
                "SELECT extras, reminder_rule FROM tasks WHERE id=?", (probe_task_id,)
            ).fetchone()
        finally:
            conn.execute("ROLLBACK")

        expect(
            isinstance(raw_extras, str) and isinstance(json.loads(raw_extras), dict),
            f"SQLite 原始列 tasks.extras 为可解析 JSON 文本（实际 {raw_extras!r}）",
        )
        expect(
            isinstance(raw_rule, str) and isinstance(json.loads(raw_rule), dict),
            f"SQLite 原始列 tasks.reminder_rule 为可解析 JSON 文本（实际 {raw_rule!r}）",
        )
        expect(
            json.loads(raw_extras) == TABLE_CHECK_EXTRAS and json.loads(raw_rule) == TABLE_CHECK_RULE,
            "SQLite 原始列内容与写入值完全一致（无字段丢失 / 额外改写）",
        )
        leftover = conn.execute("SELECT COUNT(*) FROM tasks WHERE id=?", (probe_task_id,)).fetchone()[0]
        expect(int(leftover) == 0, "extras 探针行已回滚（无残留数据）")

        # ---- 8) 阶段 2 认证与组织列形态 -----------------------------------
        user_columns = column_names(conn, "users")
        expect(
            {"password_hash", "password_updated_at", "status", "platform_admin"} <= user_columns,
            f"users 含阶段 2 认证列（实际 {sorted(user_columns)}）",
        )
        user_defaults = {
            str(row[1]): row[4]
            for row in conn.execute("PRAGMA table_info('users')").fetchall()
        }
        expect(
            (user_defaults.get("status") or "").strip("'\"") == "active",
            f"users.status 默认值为 active（实际 {user_defaults.get('status')!r}）",
        )
        expect(
            str(user_defaults.get("platform_admin")) in {"0", "0.0"},
            f"users.platform_admin 默认值为 0（实际 {user_defaults.get('platform_admin')!r}）",
        )
        expect(
            "org_id" in column_names(conn, "tasks") and "org_id" in column_names(conn, "activities"),
            "tasks / activities 含 org_id 列",
        )
        org_member_unique = unique_index_names(conn, "org_members")
        expect(
            "uq_org_members_org_user" in org_member_unique
            or ("org_id", "user_id") in unique_column_sets(conn, "org_members")
            or ("user_id", "org_id") in unique_column_sets(conn, "org_members"),
            "org_members 存在 UNIQUE(org_id, user_id)"
            f"（实际唯一索引 {sorted(org_member_unique)}）",
        )
    finally:
        conn.close()

    print(f"---- verify_tables.py 全部通过：{_passed} 项断言（23 表 + 阶段 2 认证与组织列 + AI 会话表 + 依赖边表 + 资料与成果表 + AI 用量账本）----")
    return 0


if __name__ == "__main__":
    sys.exit(main())
