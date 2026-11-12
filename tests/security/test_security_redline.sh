#!/usr/bin/env bash
# =============================================================================
# T12/T8 · 安全红线核查（只读扫描，不修改任何实现文件）
#
# ============================ 分层判定口径 ============================
# 交付红线针对「受控文件与交付包」，而不是本机运行时状态：
#   A 层（严格，必须 0 命中）：
#     A1. 源码 / 测试 / 文档 / 交付物中不得出现 Key 字面量
#         （`sk-` 前缀 + ≥16 位 Key 字符；`.env` 本身不参与源码扫描）；
#     A2. `frontend/src` 与 `frontend/dist` 不得出现 `MAAS_API_KEY`；
#     A3. `.gitignore` 必须覆盖 `.env` / `.venv` / `node_modules` / `*.db` / `dist`，
#         且不得忽略 `.env.example`。
#   B 层（本地运行时文件，允许存在但必须合规）：
#     B4. `backend/.env` 若存在：必须被 `.gitignore` 覆盖、不在交付目录内，
#         且脚本不读取/不打印其值 → `PASS-LOCAL`；
#     B5. `backend/*.db` 若存在：必须被 `*.db` 覆盖、不在交付目录内，
#         且测试必须使用 `DATABASE_PATH=<临时库>` → `PASS-LOCAL`；
#     B6. 若不存在：同样 PASS（「无本地运行时文件」）。
#
# 理由：本地 `.env`（真实 Key）与演示库 `*.db` 是运行必需文件，**不得入交付包**；
#       把它们当作「仓库内容」判 FAIL 会把运行必需与代码泄露混为一谈。
#       Key 泄露判定以「源码/交付物中的字面量」为准；本地 `.env` 只需「被忽略 + 不入包」。
#       任何 A 层命中，或 B 层「存在但未被忽略 / 在交付目录内」→ 仍 FAIL。
#
# 关于 "sk-" 误报：
#   - CSS 类名 `task-name`、`mask-border` 等英文单词天然含子串 `sk-`；
#   - 因此采用「词边界 + 至少 16 位 Key 字符」的强模式，弱模式只做诊断输出；
#   - 本检测脚本自身（含正则字面量）是唯一白名单，其他 tests 文件照常扫描。
#
# 退出码：0 = 无 FAIL（A 层全 PASS 且 B 层合规）；1 = 存在任一 FAIL。
# 用法：bash tests/security/test_security_redline.sh
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
GITIGNORE="${PROJECT_ROOT}/.gitignore"
SELF_SCRIPT="tests/security/test_security_redline.sh"

PASS_COUNT=0
PASS_LOCAL_COUNT=0
FAIL_COUNT=0
FAILED_ITEMS=()

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf '[PASS] %s\n' "$1"
}

pass_local() {
  PASS_LOCAL_COUNT=$((PASS_LOCAL_COUNT + 1))
  printf '[PASS-LOCAL] %s\n' "$1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAILED_ITEMS+=("$1")
  printf '[FAIL] %s\n' "$1"
  if [ "$#" -gt 1 ]; then
    printf '       %s\n' "$2"
  fi
}

section() {
  printf '\n--- %s ---\n' "$1"
}

echo "======================================================================"
echo " T8 安全红线核查（A 层严格 / B 层本地运行时文件）"
echo " 工程根：${PROJECT_ROOT}"
echo " 时间  ：$(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================"

# ---------------------------------------------------------------------------
# A1. 源码 / 测试 / 文档 / 交付物中的 Key 字面量（0 命中）
# ---------------------------------------------------------------------------
section "A1. 源码/交付物 Key 字面量扫描（强模式，必须 0 命中；.env 除外）"
KEY_RE='(^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}'
A_SCAN_PATHS=(
  "backend/app"
  "frontend/src"
  "tests"
  "readme"
  "codearts_proof"
  "README.md"
  "backend/.env.example"
)
A_KEY_HITS="$(
  grep -rnIE "${KEY_RE}" "${A_SCAN_PATHS[@]}" 2>/dev/null \
    | grep -v "${SELF_SCRIPT}" || true
)"
if [ -z "${A_KEY_HITS}" ]; then
  pass "A1 源码/交付物 Key 字面量 0 命中（扫描：backend/app、frontend/src、tests、readme、codearts_proof、README.md、.env.example）"
else
  fail "A1 源码/交付物发现疑似真实 Key 字面量" "${A_KEY_HITS}"
fi

# 诊断（不计入 PASS/FAIL）：弱模式命中来源说明
section "A1b. 弱模式诊断（sk-[A-Za-z0-9]，仅供说明误报来源）"
WEAK_RE='sk-[A-Za-z0-9]'
WEAK_HITS="$(
  grep -rnIE "${WEAK_RE}" "${A_SCAN_PATHS[@]}" 2>/dev/null \
    | grep -v "${SELF_SCRIPT}" | grep -v "tests/security/README.md" || true
)"
if [ -z "${WEAK_HITS}" ]; then
  printf '[INFO] 弱模式无命中\n'
else
  WEAK_LINES=$(printf '%s\n' "${WEAK_HITS}" | wc -l | tr -d ' ')
  printf '[INFO] 弱模式命中 %s 行；均为英文单词/CSS 类名子串（如 task-name、mask-border），\n' "${WEAK_LINES}"
  printf '       不是凭证。以下为前 5 行样例：\n'
  printf '%s\n' "${WEAK_HITS}" | head -5 | sed 's/^/       /'
fi

# ---------------------------------------------------------------------------
# A2. 前端源码 / 构建产物不得出现 MAAS_API_KEY
# ---------------------------------------------------------------------------
section "A2. frontend/src 不得出现 MAAS_API_KEY"
FE_SRC="${PROJECT_ROOT}/frontend/src"
if [ ! -d "${FE_SRC}" ]; then
  fail "A2 frontend/src 目录存在性" "未找到 ${FE_SRC}"
else
  FE_KEY_HITS="$(grep -rn "MAAS_API_KEY" "${FE_SRC}" 2>/dev/null || true)"
  if [ -z "${FE_KEY_HITS}" ]; then
    pass "A2 frontend/src 中 MAAS_API_KEY 无命中（grep 退出码 1 = 无匹配）"
  else
    fail "A2 frontend/src 中出现 MAAS_API_KEY" "${FE_KEY_HITS}"
  fi
fi

section "A2b. frontend/dist 不得出现 MAAS_API_KEY（交付物）"
FE_DIST="${PROJECT_ROOT}/frontend/dist"
if [ -d "${FE_DIST}" ]; then
  DIST_HITS="$(grep -rn "MAAS_API_KEY" "${FE_DIST}" 2>/dev/null || true)"
  if [ -z "${DIST_HITS}" ]; then
    pass "A2b frontend/dist 中 MAAS_API_KEY 无命中"
  else
    fail "A2b frontend/dist 中出现 MAAS_API_KEY" "${DIST_HITS}"
  fi
else
  fail "A2b frontend/dist 存在性" "未找到 ${FE_DIST}（构建应已生成 dist）"
fi

# ---------------------------------------------------------------------------
# A3. .gitignore 覆盖关键排除项
# ---------------------------------------------------------------------------
section "A3. .gitignore 覆盖项"
if [ ! -f "${GITIGNORE}" ]; then
  fail "A3 .gitignore 存在性" "未找到 ${GITIGNORE}"
else
  check_ignore() {
    local label="$1"
    local pattern="$2"
    local hit
    hit="$(grep -nE "${pattern}" "${GITIGNORE}" | head -1 || true)"
    if [ -n "${hit}" ]; then
      pass "A3 .gitignore 含 ${label}（命中：${hit}）"
    else
      fail "A3 .gitignore 缺少 ${label}" "在 ${GITIGNORE} 中未匹配到 /${pattern}/"
    fi
  }
  check_ignore ".env"         '^\.env$'
  check_ignore ".venv"        '^\.venv/?$'
  check_ignore "node_modules" '^node_modules/?$'
  check_ignore "*.db"         '^\*\.db$'
  check_ignore "dist"         '^dist/?$'
  if grep -qE '^!\.env\.example$' "${GITIGNORE}"; then
    pass "A3 .gitignore 显式放行 .env.example（负向规则）"
  else
    fail "A3 .gitignore 未放行 .env.example" "缺少 !.env.example 规则，示例文件可能被误忽略"
  fi
fi

# ---------------------------------------------------------------------------
# B4. 本地运行时文件：backend/.env（允许存在，但必须被忽略且不入包）
# ---------------------------------------------------------------------------
section "B4. backend/.env（本地运行时，PASS-LOCAL 口径）"
ENV_FILE="${PROJECT_ROOT}/backend/.env"
if [ -f "${ENV_FILE}" ]; then
  ENV_RULE="$(grep -nE '^(\.env|\.env\.\*|\*\.env|/\.env)$' "${GITIGNORE}" 2>/dev/null | head -1 || true)"
  ENV_IN_DELIVERY="no"
  case "${ENV_FILE}" in
    "${PROJECT_ROOT}/readme/"*|"${PROJECT_ROOT}/codearts_proof/"*|"${PROJECT_ROOT}/backend/app/"*|"${PROJECT_ROOT}/frontend/src/"*)
      ENV_IN_DELIVERY="yes" ;;
  esac
  ENV_REL="$(printf '%s' "${ENV_FILE}" | sed "s|^${PROJECT_ROOT}/||")"
  if [ -n "${ENV_RULE}" ] && [ "${ENV_IN_DELIVERY}" = "no" ]; then
    pass_local "backend/.env 存在且被 .gitignore 覆盖（命中规则：${ENV_RULE}）、不在交付包内；脚本未读取/未打印 Key 值（路径：${ENV_REL}）"
  else
    fail "B4 backend/.env 存在但不合规" "gitignore 命中=${ENV_RULE:-无}；在交付目录内=${ENV_IN_DELIVERY}；必须被忽略且不得入包（路径：${ENV_REL}）"
  fi
else
  pass "B4 无本地 backend/.env（仅保留 .env.example 模板）"
fi
if [ -f "${PROJECT_ROOT}/backend/.env.example" ]; then
  pass "B4 backend/.env.example 存在（占位值模板，可入交付包）"
else
  fail "B4 backend/.env.example 缺失" "交付物要求提供占位值模板"
fi

# ---------------------------------------------------------------------------
# B5. 本地演示库：backend/*.db（允许存在，但必须被忽略且测试使用临时库）
# ---------------------------------------------------------------------------
section "B5. backend/*.db（本地演示库，PASS-LOCAL 口径）"
DB_FILES="$(
  find "${PROJECT_ROOT}/backend" -maxdepth 1 -type f \
    \( -name '*.db' -o -name '*.db-journal' -o -name '*.db-wal' -o -name '*.db-shm' \
       -o -name '*.sqlite' -o -name '*.sqlite3' \) -print 2>/dev/null || true
)"
if [ -z "${DB_FILES}" ]; then
  pass "B5 无本地演示库（*.db / *.sqlite 不存在）"
else
  DB_RULE="$(grep -nE '^\*\.db$|^\*\.db-|^\*\.sqlite' "${GITIGNORE}" 2>/dev/null | tr '\n' ';' || true)"
  DB_IN_DELIVERY=""
  DB_COUNT=0
  while IFS= read -r db_file; do
    [ -z "${db_file}" ] && continue
    DB_COUNT=$((DB_COUNT + 1))
    case "${db_file}" in
      "${PROJECT_ROOT}/readme/"*|"${PROJECT_ROOT}/codearts_proof/"*|"${PROJECT_ROOT}/backend/app/"*|"${PROJECT_ROOT}/frontend/src/"*)
        DB_IN_DELIVERY="${DB_IN_DELIVERY}${db_file};" ;;
    esac
  done <<< "${DB_FILES}"

  # 测试必须使用临时库（证据：run_all.sh 的 mktemp + DATABASE_PATH，e2e 的 DATABASE_PATH）
  TEMP_DB_EVIDENCE=""
  if grep -q "DATABASE_PATH" "${PROJECT_ROOT}/tests/backend/run_all.sh" 2>/dev/null \
     && grep -q "mktemp" "${PROJECT_ROOT}/tests/backend/run_all.sh" 2>/dev/null; then
    TEMP_DB_EVIDENCE="run_all.sh(DATABASE_PATH+mktemp)"
  fi
  if grep -q "DATABASE_PATH" "${PROJECT_ROOT}/tests/security/e2e_headless.py" 2>/dev/null \
     && grep -q "mkdtemp" "${PROJECT_ROOT}/tests/security/e2e_headless.py" 2>/dev/null; then
    TEMP_DB_EVIDENCE="${TEMP_DB_EVIDENCE:+${TEMP_DB_EVIDENCE} + }e2e_headless.py(DATABASE_PATH+mkdtemp)"
  fi

  if [ -n "${DB_RULE}" ] && [ -z "${DB_IN_DELIVERY}" ] && [ -n "${TEMP_DB_EVIDENCE}" ]; then
    pass_local "本地演示库存在（${DB_COUNT} 个）且被 .gitignore 覆盖（命中规则：${DB_RULE}）、不在交付包内；测试均使用临时库（证据：${TEMP_DB_EVIDENCE}）"
  else
    fail "B5 本地演示库存在但不合规" "gitignore 命中=${DB_RULE:-无}；在交付目录内=${DB_IN_DELIVERY:-无}；临时库证据=${TEMP_DB_EVIDENCE:-无}"
  fi
fi

# ---------------------------------------------------------------------------
# B5b. 其余运行产物（日志 / 临时 / 备份 / 交换文件）仍严格 0 命中
# ---------------------------------------------------------------------------
section "B5b. 日志 / 临时 / 备份文件残留（严格）"
RESIDUE="$(
  find "${PROJECT_ROOT}" \
    \( -name .venv -o -name venv -o -name node_modules -o -name dist -o -name .git \) -prune -o \
    -type f \( \
      -name '*.log' -o -name '*.tmp' -o -name '*.temp' -o -name '*.bak' \
      -o -name '*.swp' -o -name '*.swo' -o -name '*~' \
    \) -print 2>/dev/null \
    || true
)"
if [ -z "${RESIDUE}" ]; then
  pass "B5b 无 .log / .tmp / 备份 / 交换文件残留"
else
  fail "B5b 发现运行产物残留" "${RESIDUE}"
fi

# 附加：Python 缓存目录（.pyc 属编译产物，已被 .gitignore 排除；只告警不判失败）
PYCACHE_COUNT="$(
  find "${PROJECT_ROOT}" \
    \( -name .venv -o -name venv -o -name node_modules -o -name dist -o -name .git \) -prune -o \
    -type d -name '__pycache__' -print 2>/dev/null | wc -l | tr -d ' '
)"
if [ "${PYCACHE_COUNT}" -gt 0 ]; then
  printf '[INFO] 存在 %s 个 __pycache__ 目录（已被 .gitignore 排除，不计入 FAIL）\n' "${PYCACHE_COUNT}"
fi

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
TOTAL=$((PASS_COUNT + PASS_LOCAL_COUNT + FAIL_COUNT))
echo
echo "======================================================================"
printf ' 结果：%s 通过 / %s PASS-LOCAL / %s 失败 / 共 %s 项\n' \
  "${PASS_COUNT}" "${PASS_LOCAL_COUNT}" "${FAIL_COUNT}" "${TOTAL}"
echo " 口径：A 层（源码/交付物 Key 字面量、前端 Key 变量名、.gitignore 覆盖）必须 0 命中；"
echo "       B 层（backend/.env、backend/*.db）允许存在，但必须被 .gitignore 覆盖且不入包。"
if [ "${FAIL_COUNT}" -gt 0 ]; then
  echo " 失败项："
  for item in "${FAILED_ITEMS[@]}"; do
    printf '   - %s\n' "${item}"
  done
  echo " 结论：安全红线 FAIL"
  echo "======================================================================"
  exit 1
fi
echo " 结论：安全红线 PASS（A 层 0 命中；B 层本地运行时文件合规或不存在）"
echo "======================================================================"
exit 0
