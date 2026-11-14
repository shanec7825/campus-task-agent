#!/usr/bin/env bash
# =============================================================================
# T11 前端构建门禁（契约 C-SHELL@1 / 验收 T11-①②）
#
# 依次执行：
#   1. npm run typecheck（vue-tsc --noEmit）
#   2. npm run build（vite build，正式生成 frontend/dist —— dist 由 T11 独占）
#   3. 断言 dist/index.html 存在且非空
#   4. 断言 src 内无 `: any` / `as any`
#
# 退出码语义（便于 run_all.sh / CI 判断失败阶段）：
#   0 = 全部通过
#   1 = typecheck 失败（不继续 build，避免无意义耗时）
#   2 = build 失败
#   3 = 构建产物断言失败（dist/index.html 缺失 / any 命中）
#
# 说明：本脚本不使用 `set -e`，以便逐项记录 PASS/FAIL 并输出汇总；
#       未定义变量与管道失败仍按 `set -u` / `pipefail` 视为错误。
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/../../frontend" && pwd)"

cd "${FRONTEND_DIR}" || {
  echo "[test_build] 无法进入前端目录：${FRONTEND_DIR}" >&2
  exit 1
}

PASS_COUNT=0
FAIL_COUNT=0

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf '  [PASS] %s\n' "$1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf '  [FAIL] %s\n' "$1"
}

echo "======================================================================"
echo "T11 前端构建门禁：$(pwd)"
echo "======================================================================"

# ---------------------------------------------------------------------------
# 1/4 typecheck
# ---------------------------------------------------------------------------
echo
echo "== [1/4] npm run typecheck =="
npm run typecheck
TYPECHECK_EXIT=$?

if [ "${TYPECHECK_EXIT}" -eq 0 ]; then
  pass "typecheck 通过（vue-tsc --noEmit 无类型错误）"
else
  fail "typecheck 失败（退出码 ${TYPECHECK_EXIT}）"
  echo
  echo "----------------------------------------------------------------------"
  echo "RESULT: ${PASS_COUNT} passed, ${FAIL_COUNT} failed（typecheck 失败，跳过 build）"
  exit 1
fi

# ---------------------------------------------------------------------------
# 2/4 build（正式生成 dist）
# ---------------------------------------------------------------------------
echo
echo "== [2/4] npm run build（生成 frontend/dist） =="
npm run build
BUILD_EXIT=$?

if [ "${BUILD_EXIT}" -eq 0 ]; then
  pass "build 通过（vite build 成功）"
else
  fail "build 失败（退出码 ${BUILD_EXIT}）"
  echo
  echo "----------------------------------------------------------------------"
  echo "RESULT: ${PASS_COUNT} passed, ${FAIL_COUNT} failed（build 失败，无法校验产物）"
  exit 2
fi

# ---------------------------------------------------------------------------
# 3/4 dist/index.html
# ---------------------------------------------------------------------------
echo
echo "== [3/4] 断言 dist/index.html 存在且非空 =="
if [ -s "${FRONTEND_DIR}/dist/index.html" ]; then
  DIST_BYTES="$(wc -c < "${FRONTEND_DIR}/dist/index.html" | tr -d ' ')"
  pass "dist/index.html 存在（${DIST_BYTES} 字节）"
else
  fail "dist/index.html 缺失或为空：${FRONTEND_DIR}/dist/index.html"
fi

# ---------------------------------------------------------------------------
# 4/4 禁止 any
# ---------------------------------------------------------------------------
echo
echo "== [4/4] 断言 src 内无 ': any' / 'as any' =="
ANY_HITS="$(grep -rnE ': any([^A-Za-z]|$)|as any([^A-Za-z]|$)' src || true)"
if [ -z "${ANY_HITS}" ]; then
  pass "src 内无 ': any' / 'as any' 命中"
else
  fail "src 内出现 ': any' / 'as any'（禁止弱化类型）："
  printf '%s\n' "${ANY_HITS}" | sed 's/^/         /'
fi

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
echo
echo "----------------------------------------------------------------------"
echo "RESULT: ${PASS_COUNT} passed, ${FAIL_COUNT} failed"

if [ "${FAIL_COUNT}" -ne 0 ]; then
  exit 3
fi

echo "前端构建门禁全部通过，dist 已生成：${FRONTEND_DIR}/dist"
exit 0
