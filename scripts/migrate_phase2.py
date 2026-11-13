"""阶段 2 认证与组织权限的结构升级脚本（契约 `C-MIGRATION-3@1`，需求 R7）。

用法（仓库根）：

    python scripts/migrate_phase2.py --db outputs/phase2/campus-copy.db

行为：
1. `--db` 必填；拒绝直接迁移 `backend/campus.db`，除非同时传 `--allow-real`
   并在终端交互输入确认短语；
2. 先把目标库 `shutil.copy2` 备份为 `<db>.backup-YYYYmmddHHMMSS`；
3. 通过 `init_db()` 在目标库上执行幂等结构升级（不删列、不删行、不推断组织归属）；
4. 输出 `outputs/phase2/migration_report.md`。

报告写入失败不影响已经完成的数据库升级，但脚本退出码为 1 并打印目标路径。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_DB_PATH = ROOT / "backend" / "campus.db"
REPORT_PATH = ROOT / "outputs" / "phase2" / "migration_report.md"
CONFIRM_PHRASE = "MIGRATE REAL DATABASE"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="在数据库副本上执行阶段 2 结构升级并生成迁移报告")
    parser.add_argument("--db", required=True, help="待升级的数据库副本路径（必填）")
    parser.add_argument(
        "--allow-real",
        action="store_true",
        help="允许迁移 backend/campus.db（仍需终端交互确认）",
    )
    return parser.parse_args(argv)


def _backup(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.backup-{stamp}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in names}


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _null_org_count(conn: sqlite3.Connection, table: str) -> int | None:
    if "org_id" not in _column_names(conn, table):
        return None
    return conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE org_id IS NULL').fetchone()[0]


def _collect_stats(db_path: Path) -> dict[str, object]:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = _table_counts(conn)
        users_total = tables.get("users", 0)
        legacy_total = 0
        with_password = 0
        if "users" in tables:
            columns = _column_names(conn, "users")
            if "status" in columns:
                legacy_total = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE status = 'legacy_unclaimed'"
                ).fetchone()[0]
            if "password_hash" in columns:
                with_password = conn.execute(
                    "SELECT COUNT(*) FROM users "
                    "WHERE password_hash IS NOT NULL AND TRIM(password_hash) <> ''"
                ).fetchone()[0]
        return {
            "tables": tables,
            "users_total": users_total,
            "legacy_total": legacy_total,
            "with_password": with_password,
            "without_password": users_total - with_password,
            "activities_total": tables.get("activities", 0),
            "tasks_total": tables.get("tasks", 0),
            "activities_without_org": _null_org_count(conn, "activities"),
            "tasks_without_org": _null_org_count(conn, "tasks"),
        }
    finally:
        conn.close()


def _fmt(value: int | None) -> str:
    return "（无 org_id 列）" if value is None else str(value)


def _render_report(
    db_path: Path, backup_path: Path, started_at: datetime, stats: dict[str, object]
) -> str:
    tables: dict[str, int] = stats["tables"]  # type: ignore[assignment]
    table_lines = "\n".join(f"| `{name}` | {count} |" for name, count in tables.items()) or "| （无表） | 0 |"
    return f"""# 阶段 2 数据库结构升级报告

- 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
- 升级开始时间：{started_at.strftime("%Y-%m-%d %H:%M:%S")}
- 源库路径（升级副本）：`{db_path}`
- 备份路径：`{backup_path}`
- 升级方式：`init_db()` 幂等增量迁移（只加列、加索引、补状态，不删列、不删行）

## 表清单与行数

| 表名 | 行数 |
| --- | --- |
{table_lines}

## 用户

| 指标 | 数量 |
| --- | --- |
| 用户总数 | {stats["users_total"]} |
| legacy 用户数（`status = 'legacy_unclaimed'`） | {stats["legacy_total"]} |
| 有密码用户数 | {stats["with_password"]} |
| 无密码用户数 | {stats["without_password"]} |

## 活动与任务的组织归属

| 指标 | 数量 |
| --- | --- |
| 活动总数 | {stats["activities_total"]} |
| 无组织活动数（`org_id IS NULL`） | {_fmt(stats["activities_without_org"])} |
| 任务总数 | {stats["tasks_total"]} |
| 无组织任务数（`org_id IS NULL`） | {_fmt(stats["tasks_without_org"])} |

## 结论

结构升级完成；组织归属未自动推断。
"""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_path = Path(args.db).expanduser()
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path = db_path.resolve()

    if not db_path.is_file():
        raise SystemExit(f"数据库副本不存在：{db_path}")

    if db_path == REAL_DB_PATH.resolve():
        if not args.allow_real:
            raise SystemExit(
                "拒绝直接迁移 backend/campus.db；请在副本上执行，或同时传 --allow-real 并交互确认"
            )
        print(f"即将迁移真实数据库：{db_path}")
        answer = input(f"输入 {CONFIRM_PHRASE} 后回车以继续：").strip()
        if answer != CONFIRM_PHRASE:
            raise SystemExit("未获得确认，已取消迁移")

    started_at = datetime.now()
    backup_path = _backup(db_path)
    print(f"已备份：{backup_path}")

    os.environ["DATABASE_PATH"] = str(db_path)
    sys.path.insert(0, str(ROOT / "backend"))
    from app.db import init_db  # noqa: E402  （必须在 DATABASE_PATH 生效之后再导入）

    init_db()
    print(f"结构升级完成：{db_path}")

    stats = _collect_stats(db_path)
    report = _render_report(db_path, backup_path, started_at, stats)
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
    except OSError as exc:
        print(f"迁移已完成，但报告写入失败：{exc}", file=sys.stderr)
        print(f"报告目标路径：{REPORT_PATH}", file=sys.stderr)
        return 1

    print(f"迁移报告：{REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())