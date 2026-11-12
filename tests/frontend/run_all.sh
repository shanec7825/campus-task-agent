#!/usr/bin/env bash
# =============================================================================
# T8 前端验证一键入口：构建门禁 + 静态契约对齐 + 语音算法单测
#
# 用法：
#   bash campus-task-agent/tests/frontend/run_all.sh
#   PYTHON_BIN=/path/to/python bash campus-task-agent/tests/frontend/run_all.sh
#
# 退出码语义：
#   0 = 三项全部通过
#   1 = 构建门禁（typecheck / build / dist / any）失败
#   2 = 静态契约对齐（check_contracts.py）失败
#   3 = 语音切片算法单测（tsc 编译 / node 断言）失败
#
# 说明：脚本自己推导 frontend 目录，可在任意工作目录执行；
#       `set -e` 用于保证前一阶段失败时立即中止，不产生误导性的"全部通过"。
#       端口资源：本脚本不启动任何服务（联调冒烟见 MANUAL_CHECKLIST.md）。
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/../../frontend" && pwd)"
BACKEND_VENV_PYTHON="${SCRIPT_DIR}/../../backend/.venv/Scripts/python.exe"

# Python 解释器优先级：显式 PYTHON_BIN > 后端 .venv > python3 > python
# check_contracts.py 只用标准库，任意 Python 3.9+ 均可运行。
resolve_python() {
  if [ -n "${PYTHON_BIN:-}" ]; then
    printf '%s' "${PYTHON_BIN}"
    return 0
  fi
  if [ -x "${BACKEND_VENV_PYTHON}" ]; then
    printf '%s' "${BACKEND_VENV_PYTHON}"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s' "python"
    return 0
  fi
  return 1
}

if ! PYTHON="$(resolve_python)"; then
  echo "[run_all] 未找到 Python 3 解释器；请设置 PYTHON_BIN 或使用 backend/.venv" >&2
  exit 1
fi

echo "######################################################################"
echo "# T8 前端验证：构建门禁 + 静态契约对齐 + 语音算法单测"
echo "# 前端目录：${FRONTEND_DIR}"
echo "# Python  ：${PYTHON}"
echo "######################################################################"

echo
echo ">>> [步骤 1/2] 构建门禁（test_build.sh）"
# 注意：此处不要写成 `if ! cmd; then`，否则 `$?` 会被取反逻辑覆盖为 0
if bash "${SCRIPT_DIR}/test_build.sh"; then
  :
else
  BUILD_EXIT=$?
  echo
  echo "[run_all] 步骤 1/2 失败：构建门禁未通过（test_build.sh 退出码 ${BUILD_EXIT}）" >&2
  exit 1
fi

echo
echo ">>> [步骤 2/2] 静态契约对齐（check_contracts.py）"
if "${PYTHON}" "${SCRIPT_DIR}/check_contracts.py" --frontend "${FRONTEND_DIR}"; then
  :
else
  CONTRACT_EXIT=$?
  echo
  echo "[run_all] 步骤 2/2 失败：静态契约对齐未通过（check_contracts.py 退出码 ${CONTRACT_EXIT}）" >&2
  exit 2
fi

echo
# ---------------------------------------------------------------------------
# 步骤 3/3：语音切片算法单测（C-VOICEUI@2）
#   1. tsc 单文件编译 src/utils/voiceSlicer.ts → tests/frontend/.tmp-voice
#   2. node check_voice_slicer.cjs 执行 7 组切片 + 5 常量 + 旧函数名零命中
#   3. 无论成功失败都删除 .tmp-voice（不污染仓库）
# ---------------------------------------------------------------------------
echo
echo ">>> [步骤 3/3] 语音切片算法单测（tsc 编译 + node 断言）"
# 注意：不能放在 frontend/ 内（其 package.json 为 type=module，CommonJS 产物会被当 ESM）
TMP_VOICE="${SCRIPT_DIR}/.tmp-voice"
rm -rf "${TMP_VOICE}"
mkdir -p "${TMP_VOICE}"
VOICE_CLEANUP_DONE=0
cleanup_voice() {
  rm -rf "${TMP_VOICE}"
  VOICE_CLEANUP_DONE=1
}
trap cleanup_voice EXIT
if (
  cd "${FRONTEND_DIR}"
  npx tsc src/utils/voiceSlicer.ts --outDir "${TMP_VOICE}" --module commonjs --target es2020 --skipLibCheck
); then
  :
else
  echo "[run_all] 步骤 3/3 失败：voiceSlicer.ts 单文件编译失败" >&2
  exit 3
fi
VOICE_JS="$(find "${TMP_VOICE}" -name 'voiceSlicer.js' -print -quit)"
if [ -z "${VOICE_JS}" ]; then
  echo "[run_all] 步骤 3/3 失败：编译产物 voiceSlicer.js 未找到（${TMP_VOICE}）" >&2
  exit 3
fi
if node "${SCRIPT_DIR}/check_voice_slicer.cjs" "${VOICE_JS}" "${FRONTEND_DIR}/src"; then
  :
else
  VOICE_EXIT=$?
  echo "[run_all] 步骤 3/3 失败：语音切片算法单测未通过（exit ${VOICE_EXIT}）" >&2
  exit 3
fi
cleanup_voice
trap - EXIT

echo
echo "######################################################################"
echo "# ALL PASS：构建门禁 + 静态契约对齐 + 语音算法单测均通过"
echo "# 产物：${FRONTEND_DIR}/dist/index.html（正式 dist）"
echo "# 人工验收项见：${SCRIPT_DIR}/MANUAL_CHECKLIST.md"
echo "######################################################################"
exit 0