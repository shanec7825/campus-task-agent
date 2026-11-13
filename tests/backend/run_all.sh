#!/usr/bin/env bash
# T5 后端契约与集成验证 · 统一入口（第三轮迭代终验）
#
# 做的事（严格对应 plan T10 acceptance_and_local_checks）：
#   1. 用 mktemp 目录下的**临时 SQLite 库** + MAAS_MOCK=1 + RUN_SCHEDULER=0 启动后端，
#      端口 8040（T5 独占；不占用 8000/5173，避免与人工演示冲突）；
#   2. 依次执行 6 个验证脚本（任一失败立即以非 0 退出，set -e）：
#      verify_tables（9 表）→ test_applications（R16 矩阵）→ test_api_e2e（apply/approve 全流程）
#      → test_agent_mock（P1 规则回归）→ test_agent_incremental（增量/纯值/红线）
#      → test_sse_and_reminder（SSE + 三级催办）；
#   3. 额外做一次「KB 不过滤模式」的观测运行（端口 8041 + KB_MIN_SIMILARITY=0），
#      仅记录差异，不作为失败判据（plan：threshold 语义由 Leader 裁定为默认 0.6 过滤）；
#   4. 退出时停止后端进程、删除临时库与日志（不触碰 .venv / node_modules）。
#
# 用法：bash campus-task-agent/tests/backend/run_all.sh
# 可选环境变量：T10_PORT（默认 8040）、T10_KB_PORT（默认 8041）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$AGENT_DIR/backend"
if [ -n "${PYTHON_BIN:-}" ]; then
  PY="$PYTHON_BIN"
elif [ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ]; then
  PY="$BACKEND_DIR/.venv/Scripts/python.exe"
elif [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  PY="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  PY="$(command -v python)"
fi
PORT="${T10_PORT:-8040}"
KB_PORT="${T10_KB_PORT:-8041}"

TMP_DIR="$(mktemp -d)"
LOG_FILE="$TMP_DIR/t10-server.log"
KB_LOG_FILE="$TMP_DIR/t10-kb-server.log"

SERVER_PID=""
KB_SERVER_PID=""

# MSYS（git-bash）把 POSIX 路径传给原生 python.exe 时行为不稳定，统一转成 Windows 路径
to_win_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1"
  else
    printf '%s' "$1"
  fi
}

DB_PATH="$(to_win_path "$TMP_DIR/t10.db")"
BACKEND_DIR_WIN="$(to_win_path "$BACKEND_DIR")"

port_in_use() {
  "$PY" - "$1" <<'PY'
import socket
import sys

sock = socket.socket()
sock.settimeout(0.4)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    print("no")
else:
    print("yes")
finally:
    sock.close()
PY
}

wait_health() {
  "$PY" - "http://127.0.0.1:$1/api/health" "$1" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

url, port = sys.argv[1], sys.argv[2]
for _ in range(80):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            body = json.loads(response.read().decode("utf-8"))
        if body.get("code") == 0:
            print(f"INFO: 后端 {port} 健康检查通过（mock={body['data'].get('mock')}）")
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        time.sleep(0.5)
print(f"FAIL: 后端 {port} 健康检查超时（{url}）")
raise SystemExit(1)
PY
}

force_kill_port() {
  "$PY" - "$1" <<'PY'
import subprocess
import sys

port = sys.argv[1]
try:
    output = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace").stdout
except Exception:
    raise SystemExit(0)
pids = set()
for line in output.splitlines():
    parts = line.split()
    if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
        pids.add(parts[4])
for pid in pids:
    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
print(f"INFO: 端口 {port} 强制清理 {len(pids)} 个残留进程")
PY
}

stop_server() {
  local pid="${1:-}"
  local port="${2:-}"
  # 只清理「本脚本启动过」的进程：pid 为空说明从未启动，绝不能按端口强杀（避免误伤他人进程）
  if [ -z "$pid" ]; then
    return 0
  fi
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  if [ -n "$port" ]; then
    for _ in $(seq 1 20); do
      if [ "$(port_in_use "$port")" = "no" ]; then
        return 0
      fi
      sleep 0.2
    done
    force_kill_port "$port"
  fi
  return 0
}

cleanup() {
  local code=$?
  trap - EXIT INT TERM
  echo
  echo "===== 清理 ====="
  stop_server "$SERVER_PID" "$PORT"
  stop_server "$KB_SERVER_PID" "$KB_PORT"
  rm -rf "$TMP_DIR"
  if [ -d "$TMP_DIR" ]; then
    echo "WARN: 临时目录未删除成功：$TMP_DIR"
  else
    echo "INFO: 已停止 $PORT/$KB_PORT 后端进程；临时数据库与日志已删除：$TMP_DIR"
  fi
  if [ "$code" -ne 0 ]; then
    echo "FAIL: 验证未通过（exit=$code）"
  fi
  exit "$code"
}
trap cleanup EXIT INT TERM

run_step() {
  local label="$1"
  local script="$2"
  echo
  echo "===== $label：$script ====="
  "$PY" "$SCRIPT_DIR/$script"
}

# --------------------------------------------------------------------------- #
# 前置检查
# --------------------------------------------------------------------------- #
echo "===== T5 后端契约与集成验证开始 ====="
echo "INFO: 项目根 = $AGENT_DIR"
echo "INFO: 后端目录 = $BACKEND_DIR"
echo "INFO: 解释器 = $PY"
"$PY" -V

if [ ! -x "$PY" ]; then
  echo "FAIL: 未找到后端虚拟环境解释器：$PY"
  exit 1
fi
if [ "$(port_in_use "$PORT")" = "yes" ]; then
  echo "FAIL: 端口 $PORT 已被占用（T5 约定 8040；请先停止占用进程，或设置 T10_PORT 换端口）"
  exit 1
fi


echo "INFO: 临时数据库 = $DB_PATH"

# --------------------------------------------------------------------------- #
# 启动被测后端（临时库 + mock + 不启动调度器）
# --------------------------------------------------------------------------- #
(
  cd "$BACKEND_DIR"
  DATABASE_PATH="$DB_PATH" \
  MAAS_MOCK=1 \
  RUN_SCHEDULER=0 \
  MAAS_API_KEY="" \
  exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
) > "$LOG_FILE" 2>&1 &
SERVER_PID=$!

wait_health "$PORT"

export T10_BASE_URL="http://127.0.0.1:$PORT"
export T10_DB_PATH="$DB_PATH"
export T10_BACKEND_DIR="$BACKEND_DIR_WIN"
export DATABASE_PATH="$DB_PATH"

# --------------------------------------------------------------------------- #
# 依次执行 6 个验证脚本（set -e：任一失败即跳到 cleanup 并以非 0 退出）
# --------------------------------------------------------------------------- #
run_step "① 建表与数据形态（9 表 + task_applications 唯一约束）" "verify_tables.py"
run_step "② 报名审批矩阵（R16-AC1~AC16）" "test_applications.py"
run_step "③ REST 全流程与错误码矩阵（apply/approve 语义）" "test_api_e2e.py"
run_step "④ Agent mock 规则与知识库" "test_agent_mock.py"
run_step "⑤ 增量解析 / 纯值 / 追溯红线" "test_agent_incremental.py"
run_step "⑥ 真 SSE 推送与三级催办" "test_sse_and_reminder.py"

# --------------------------------------------------------------------------- #
# 观测：KB 过滤模式差异（不作为失败判据）
# --------------------------------------------------------------------------- #
echo
echo "===== 观测：KB 过滤模式差异（KB_MIN_SIMILARITY=0，端口 $KB_PORT，不计入失败）====="
if [ "$(port_in_use "$KB_PORT")" = "yes" ]; then
  echo "SKIP: 端口 $KB_PORT 已被占用，跳过 KB 观测（可设置 T10_KB_PORT 换端口；不影响主验证结论）"
else
  set +e
  (
    cd "$BACKEND_DIR"
    DATABASE_PATH="$DB_PATH" \
    MAAS_MOCK=1 \
    RUN_SCHEDULER=0 \
    MAAS_API_KEY="" \
    KB_MIN_SIMILARITY=0 \
    exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$KB_PORT"
  ) > "$KB_LOG_FILE" 2>&1 &
  KB_SERVER_PID=$!

  if wait_health "$KB_PORT"; then
    T10_BASE_URL="http://127.0.0.1:$KB_PORT" "$PY" "$SCRIPT_DIR/test_agent_mock.py" --kb-mode=unfiltered
    echo "INFO: KB 不过滤模式观测完成（exit=$?）"
  else
    echo "SKIP: KB 观测后端未能启动，跳过该观测（不影响主验证结论）"
  fi
  set -e
fi

echo
echo "===== T5 全部主验证通过（9 表 / 报名审批 / 链式增量 / SSE 催办） ====="
