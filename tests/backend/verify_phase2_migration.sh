#!/usr/bin/env bash
# 阶段 2 数据库副本迁移验证入口
#
# 做的事：
#   1. 在 outputs/phase2/ 下生成隔离源库（复用 scripts/seed_phase1_demo.py，不触碰 backend/campus.db）；
#   2. 复制为副本，运行 scripts/migrate_phase2.py，产出迁移报告；
#   3. 校验数据保留（用户/任务/活动/报名/成员/积分行数不变）、新表与 org_id 列存在、
#      legacy 账号标记、索引存在；
#   4. 再次执行迁移，校验行数不变（可重跑）；
#   5. 校验备份文件存在。
#
# 用法：bash tests/backend/verify_phase2_migration.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT="$ROOT/outputs/phase2"
PY="${PYTHON_BIN:-python}"

mkdir -p "$OUT"
rm -f "$OUT/src.db" "$OUT/copy.db" "$OUT"/copy.db.backup-* "$OUT/migration_report.md"

echo "===== 阶段 2 迁移副本验证 ====="
echo "INFO: 项目根 = $ROOT"
echo "INFO: 解释器 = $PY"

to_win() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

SRC="$(to_win "$OUT/src.db")"
COPY="$(to_win "$OUT/copy.db")"
export DATABASE_PATH="$SRC"

cd "$ROOT"
"$PY" scripts/seed_phase1_demo.py

cp "$OUT/src.db" "$OUT/copy.db"

# 迁移前快照
"$PY" - "$COPY" > "$OUT/before.json" <<'PY'
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
def count(t):
    try:
        return db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    except sqlite3.Error:
        return None
print(json.dumps({t: count(t) for t in [
    "users", "tasks", "activities", "task_applications", "task_members", "credit_logs", "checkins"
]}, ensure_ascii=False))
PY

"$PY" scripts/migrate_phase2.py --db "$COPY"

# 迁移后校验
"$PY" - "$COPY" "$OUT/before.json" <<'PY'
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
before = json.load(open(sys.argv[2], encoding="utf-8"))
failures = []

def count(t):
    return db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

for table, old in before.items():
    if old is None:
        continue
    now = count(table)
    if now != old:
        failures.append(f"{table} 行数变化 {old} -> {now}")

tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
for required in ["organizations", "org_members", "invitations", "user_sessions", "password_resets"]:
    if required not in tables:
        failures.append(f"缺少表 {required}")

def cols(table):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}

for col in ["password_hash", "password_updated_at", "status", "platform_admin"]:
    if col not in cols("users"):
        failures.append(f"users 缺少列 {col}")
for table in ["tasks", "activities"]:
    if "org_id" not in cols(table):
        failures.append(f"{table} 缺少列 org_id")

legacy = db.execute("SELECT COUNT(*) FROM users WHERE password_hash IS NULL AND status='legacy_unclaimed'").fetchone()[0]
expected = db.execute("SELECT COUNT(*) FROM users WHERE password_hash IS NULL").fetchone()[0]
if legacy != expected:
    failures.append(f"legacy 标记数量不符 {legacy} != {expected}")

indexes = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
for idx in ["ix_tasks_org_id", "ix_activities_org_id", "ix_org_members_user_id",
            "ix_invitations_org_id", "ix_user_sessions_user_id", "ix_password_resets_user_id"]:
    if idx not in indexes:
        failures.append(f"缺少索引 {idx}")

print(json.dumps({"legacy": legacy, "tables": len(tables), "failures": failures}, ensure_ascii=False))
raise SystemExit(1 if failures else 0)
PY

# 可重跑：再次执行并校验行数不变
AFTER1="$OUT/after1.json"
"$PY" - "$COPY" > "$AFTER1" <<'PY'
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
print(json.dumps({t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ["users", "tasks", "activities", "organizations", "user_sessions"]}, ensure_ascii=False))
PY
"$PY" scripts/migrate_phase2.py --db "$COPY" >/dev/null
"$PY" - "$COPY" "$AFTER1" <<'PY'
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
before = json.load(open(sys.argv[2], encoding="utf-8"))
failures = [f"{t} {old} -> {new}" for t, old in before.items()
            if (new := db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) != old]
print("SECOND_RUN: " + ("PASS" if not failures else "FAIL " + "; ".join(failures)))
raise SystemExit(1 if failures else 0)
PY

if ls "$OUT"/copy.db.backup-* >/dev/null 2>&1; then
  echo "PASS: 备份文件存在"
else
  echo "FAIL: 未找到备份文件"; exit 1
fi

if [ -f "$OUT/migration_report.md" ]; then
  echo "PASS: 迁移报告存在 outputs/phase2/migration_report.md"
else
  echo "FAIL: 未生成迁移报告"; exit 1
fi

echo "===== 阶段 2 迁移副本验证通过 ====="