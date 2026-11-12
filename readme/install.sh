#!/usr/bin/env bash
# =============================================================================
# 校园任务协同 AI Agent · 一键安装脚本（Linux / macOS / Windows git-bash）
#
# 契约：C-DELIVERY@1（plan.md 2.2.14）；启动参数与 C-BOOT@1 / C-SHELL@1 一致
#
# 行为：
#   1. 由脚本位置推导工程根（脚本所在目录的上一级），可在任意目录执行；
#   2. 优先使用 python3.12 / python3.11 创建 backend/.venv（已存在则保留，不删除）；
#   3. pip install -r requirements.txt；
#   4. cd frontend && npm install（node_modules 已存在则保留）；
#   5. 在 backend/ 下调用 app.db.init_db() 建 8 张表（幂等）；
#   6. 打印 .env 配置提示与两条启动命令。
#
# 明确不做：不自动创建 backend/.env（避免误把真实 Key 提交进仓库）。
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"
VENV_DIR="${BACKEND_DIR}/.venv"

SYS_PY=""
PY_VER=""
VENV_PY=""

python_version() {
  # 输出 "3.12" 这类主次版本号；失败返回非 0
  "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null
}

venv_python() {
  # Windows venv 布局为 Scripts/python.exe；POSIX 为 bin/python
  local candidate
  for candidate in "${VENV_DIR}/Scripts/python.exe" "${VENV_DIR}/bin/python"; do
    if [ -x "${candidate}" ]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

try_python() {
  # $1 = 解释器命令名；成功则设置 SYS_PY / PY_VER
  local candidate="$1" version
  command -v "${candidate}" >/dev/null 2>&1 || return 1
  version="$(python_version "${candidate}")" || return 1
  [ -n "${version}" ] || return 1
  # 最低要求 Python 3.10
  "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' \
    >/dev/null 2>&1 || return 1
  SYS_PY="${candidate}"
  PY_VER="${version}"
  return 0
}

echo "== 校园任务协同 AI Agent · 一键安装 =="
echo "工程根: ${PROJECT_ROOT}"
echo

# --- 前置检查 ---------------------------------------------------------------
if [ ! -f "${BACKEND_DIR}/requirements.txt" ]; then
  echo "[错误] 未找到 backend/requirements.txt，请确认脚本位于工程根的 readme/ 目录下。" >&2
  exit 1
fi
if [ ! -f "${FRONTEND_DIR}/package.json" ]; then
  echo "[错误] 未找到 frontend/package.json，请确认脚本位于工程根的 readme/ 目录下。" >&2
  exit 1
fi

# --- 1) 选择 Python 解释器 ---------------------------------------------------
# 优先 3.12 / 3.11（依赖轮子最完整），其次 3.13，最后退回系统 python3 / python
for candidate in python3.12 python3.11 python3.13 python3 python; do
  if try_python "${candidate}"; then
    break
  fi
done

if [ -z "${SYS_PY}" ]; then
  echo "[错误] 未找到可用的 Python 解释器（要求 >= 3.10）。" >&2
  echo "       请安装 Python 3.11 或 3.12 后重试：https://www.python.org/downloads/" >&2
  exit 1
fi

echo "[环境] 使用解释器: ${SYS_PY}（Python ${PY_VER}）"

case "${PY_VER}" in
  3.14|3.15)
    echo "[警告] 检测到 Python ${PY_VER}：部分依赖（pydantic-core / sqlalchemy）可能缺少预编译轮子，"
    echo "       安装失败时请改装 Python 3.11 / 3.12 并重建 backend/.venv（详见 readme/README.md 常见问题）。"
    ;;
esac

# git-bash 陷阱：若 python 解析到 MSYS2/mingw 的解释器，venv 会生成 bin/ 布局
if [ "${OS:-}" = "Windows_NT" ]; then
  PY_PATH="$(command -v "${SYS_PY}" || true)"
  case "${PY_PATH}" in
    *msys*|*mingw*|/usr/bin/*)
      echo "[提示] 当前 python 指向 ${PY_PATH}（可能是 MSYS2/mingw 解释器）。"
      echo "       若生成的 .venv 中没有 Scripts/python.exe，请改用官方 CPython 显式创建，见 readme/README.md。"
      ;;
  esac
fi
echo

# --- 2) 创建虚拟环境（幂等，不删除已存在内容）--------------------------------
if VENV_PY="$(venv_python)"; then
  echo "[1/4] [跳过] 已存在 backend/.venv（${VENV_PY}），保留现有环境不删除"
else
  if [ -e "${VENV_DIR}" ]; then
    echo "[1/4] [提示] backend/.venv 已存在但缺少 Python 可执行文件，尝试就地补建（不删除已有内容）"
  else
    echo "[1/4] 创建虚拟环境 backend/.venv ..."
  fi
  "${SYS_PY}" -m venv "${VENV_DIR}"
  if ! VENV_PY="$(venv_python)"; then
    echo "[错误] 虚拟环境创建后仍未找到解释器（期望 .venv/Scripts/python.exe 或 .venv/bin/python）。" >&2
    echo "       Windows + git-bash 下请改用官方 CPython 创建，见 readme/README.md 常见问题 2。" >&2
    exit 1
  fi
fi
echo "       使用 ${VENV_PY}"
echo

# --- 3) 后端依赖 --------------------------------------------------------------
echo "[2/4] 安装后端依赖（pip install -r requirements.txt）..."
if ! "${VENV_PY}" -m pip install --disable-pip-version-check --quiet --upgrade pip; then
  echo "[提示] pip 自升级失败（离线环境可忽略），继续使用当前 pip 版本"
fi
if ! ( cd "${BACKEND_DIR}" && "${VENV_PY}" -m pip install --disable-pip-version-check -r requirements.txt ); then
  echo "[错误] 后端依赖安装失败。" >&2
  echo "       若当前为 Python 3.14，常见原因是 pydantic-core / sqlalchemy 缺少预编译轮子；" >&2
  echo "       请安装 Python 3.11 或 3.12，删除 backend/.venv 后重新运行本脚本。" >&2
  exit 1
fi
echo

# --- 4) 前端依赖 --------------------------------------------------------------
echo "[3/4] 安装前端依赖（npm install）..."
if ! command -v npm >/dev/null 2>&1; then
  echo "[错误] 未找到 npm，请先安装 Node.js（>= 18）：https://nodejs.org/" >&2
  exit 1
fi
if [ -d "${FRONTEND_DIR}/node_modules" ]; then
  echo "       [跳过] 已存在 frontend/node_modules，保留现有依赖不删除"
  echo "       如需更新依赖，请手动执行: cd frontend && npm install"
else
  if ! ( cd "${FRONTEND_DIR}" && npm install ); then
    echo "[错误] npm install 失败，请检查网络或 npm 镜像配置（npm config set registry https://registry.npmmirror.com）。" >&2
    exit 1
  fi
fi
echo

# --- 5) 初始化 SQLite ---------------------------------------------------------
echo "[4/4] 初始化 SQLite（backend/campus.db，幂等建表）..."
if ! ( cd "${BACKEND_DIR}" && "${VENV_PY}" -c "from app.db import init_db; init_db()" ); then
  echo "[错误] 数据库初始化失败，请检查 backend/app/db.py 与 app/models.py 是否完整。" >&2
  exit 1
fi
echo

# --- 6) 完成提示（不自动创建 .env）-------------------------------------------
cat <<'EOF'
==================================================================
安装完成。脚本未自动创建 backend/.env（避免真实 Key 被误提交）。

下一步：
  1) 配置环境变量（二选一）：
     - 真实 MaaS 调用：cp backend/.env.example backend/.env
       然后把 MAAS_API_KEY / MAAS_BASE_URL / MAAS_MODEL 改成真实值；
     - 离线演示：不创建 .env，直接设置 MAAS_MOCK=1 运行（示例文件默认即为 1）。

  2) 启动后端（终端 1，端口 8000，以下命令在工程根目录执行）：
     cd backend
     .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
     # macOS / Linux 请将解释器换成 .venv/bin/python

  3) 启动前端（终端 2，端口 5173，同上在工程根目录执行）：
     cd frontend
     npm run dev

  4) 浏览器打开 http://localhost:5173 ，演示账号 teacher01 / student01
     （首次登录自动建号，无需密码）。

  健康检查：curl -s http://127.0.0.1:8000/api/health
==================================================================
EOF