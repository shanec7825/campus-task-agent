"""SQLAlchemy 引擎、会话与建表入口（契约 `C-BOOT@1` 第 2 条、`C-MIGRATION@1`）。

DATABASE_PATH 支持通过环境变量覆盖（自动化验收使用临时路径，避免污染开发库）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# 在任何配置读取之前加载 backend/.env（README 指导的配置来源）。
# 仅当文件存在时读取；override=False 保证 shell 注入的环境变量优先（自动化验收用）。
BACKEND_DIR = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env", override=False)
except ImportError:  # pragma: no cover - python-dotenv 缺失时退化为纯环境变量
    pass

DEFAULT_DATABASE_PATH = "./campus.db"


def _database_url() -> str:
    """把配置的路径转换为 SQLite URL（统一使用正斜杠，兼容 Windows 绝对路径）。"""
    raw_path = os.getenv("DATABASE_PATH", DEFAULT_DATABASE_PATH).strip() or DEFAULT_DATABASE_PATH
    normalized = raw_path.replace("\\", "/")
    # sqlite:/// 后跟相对路径；绝对路径（C:/x.db 或 /x.db）同样适用
    return f"sqlite:///{normalized}"


DATABASE_PATH = os.getenv("DATABASE_PATH", DEFAULT_DATABASE_PATH)

engine = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

Base = declarative_base()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每次请求一个会话，请求结束后关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _column_names(conn, table: str) -> set[str]:
    """返回已存在表的列名集合；表不存在时返回空集合。"""
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _table_exists(conn, table: str) -> bool:
    return bool(_column_names(conn, table))


_ADD_NOTIFICATIONS_DEDUPE_KEY = "ALTER TABLE notifications ADD COLUMN dedupe_key TEXT"

_CREATE_DEDUPE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_dedupe_key "
    "ON notifications(dedupe_key)"
)

# 旧库的 task_members 由 CREATE TABLE 内联唯一约束建立，索引名是 sqlite_autoindex_*；
# 这里补一个契约要求的具名唯一索引，便于读取 PRAGMA index_list 校验。
_CREATE_TASK_MEMBERS_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_members_task_user "
    "ON task_members(task_id, user_id)"
)

# legacy 任务（有 assignee_id 但没有任何 approved 报名）补一条 approved 报名。
# 只回填 task_id/user_id/status/created_at：decided_at/decided_by 留 NULL，
# 迁移不臆造审批人与审批时间。`INSERT OR IGNORE` 依赖 `uq_task_applications_task_user`，
# 保证重复执行不新增行、不改动既有行。
_BACKFILL_LEGACY_APPLICATIONS = """
INSERT OR IGNORE INTO task_applications (task_id, user_id, status, created_at)
SELECT t.id, t.assignee_id, 'approved',
       COALESCE(t.created_at, datetime('now','localtime'))
  FROM tasks AS t
 WHERE t.assignee_id IS NOT NULL
   AND NOT EXISTS (
       SELECT 1 FROM task_applications AS a
        WHERE a.task_id = t.id AND a.status = 'approved'
   )
"""

# 每个 approved 报名补一条成员执行行；状态只按 tasks 的当前状态映射一次，
# 时间戳留空（迁移不臆造 submitted_at/verified_at）。
_BACKFILL_MEMBERS = """
INSERT OR IGNORE INTO task_members
       (task_id, user_id, status, rejection_reason, submitted_at, verified_at, updated_at)
SELECT a.task_id, a.user_id,
       CASE t.status
            WHEN 'verified' THEN 'verified'
            WHEN 'submitted' THEN 'submitted'
            WHEN 'in_progress' THEN 'in_progress'
            ELSE 'not_started'
       END,
       NULL, NULL, NULL, datetime('now','localtime')
  FROM task_applications AS a
  LEFT JOIN tasks AS t ON t.id = a.task_id
 WHERE a.status = 'approved'
   AND NOT EXISTS (
       SELECT 1 FROM task_members AS m
        WHERE m.task_id = a.task_id AND m.user_id = a.user_id
   )
"""


def _migrate(conn) -> None:
    """幂等增量迁移（契约 `C-MIGRATION@1`）：只加列 / 加索引 / 补行，不删列不删行。"""
    if _table_exists(conn, "notifications") and "dedupe_key" not in _column_names(conn, "notifications"):
        conn.exec_driver_sql(_ADD_NOTIFICATIONS_DEDUPE_KEY)
    if _table_exists(conn, "notifications"):
        conn.exec_driver_sql(_CREATE_DEDUPE_INDEX)

    if _table_exists(conn, "task_members"):
        conn.exec_driver_sql(_CREATE_TASK_MEMBERS_UNIQUE_INDEX)

    if _table_exists(conn, "task_applications") and _table_exists(conn, "tasks"):
        conn.exec_driver_sql(_BACKFILL_LEGACY_APPLICATIONS)

    if (
        _table_exists(conn, "task_members")
        and _table_exists(conn, "task_applications")
        and _table_exists(conn, "tasks")
    ):
        conn.exec_driver_sql(_BACKFILL_MEMBERS)


def init_db() -> None:
    """建表 + 幂等迁移（可重复调用）。调用前必须先 import app.models 以注册全部表。

    ``Base.metadata.create_all`` 创建缺失的表（含 ``task_members``）；随后
    ``_migrate`` 对 P1 已存在的旧库补齐 ``notifications.dedupe_key``、去重索引、
    具名唯一索引 ``uq_task_members_task_user``、legacy ``approved`` 报名与逐人成员行。
    全程不使用 DROP / 删列 / 删行，
    因此对同一数据库重复执行不会产生重复数据。
    """
    from app import models  # noqa: F401  （注册 ORM 映射，避免循环导入）

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _migrate(conn)