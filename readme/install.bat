@echo off
rem ============================================================================
rem 校园任务协同 AI Agent · 一键安装脚本（Windows cmd，不依赖 WSL）
rem
rem 契约：C-DELIVERY@1（plan.md 2.2.14）；启动参数与 C-BOOT@1 / C-SHELL@1 一致
rem 行为与 install.sh 等价：
rem   1. 由脚本位置推导工程根（脚本所在目录的上一级）；
rem   2. 优先 py -3.12 / py -3.11 创建 backend\.venv（已存在则保留，不删除）；
rem   3. pip install -r requirements.txt；
rem   4. pushd frontend + call npm install（node_modules 已存在则保留）；
rem   5. pushd backend + 调用 init_db() 建表（幂等）；
rem   6. 打印 .env 提示与两条启动命令。
rem 明确不做：不自动创建 backend\.env。
rem ============================================================================
chcp 65001 >nul
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
set "BACKEND_DIR=%PROJECT_ROOT%\backend"
set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"
set "VENV_DIR=%BACKEND_DIR%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

echo == 校园任务协同 AI Agent · 一键安装 ==
echo 工程根: %PROJECT_ROOT%
echo.

rem ---- 前置检查 -------------------------------------------------------------
if not exist "%BACKEND_DIR%\requirements.txt" (
  echo [错误] 未找到 backend\requirements.txt，请确认脚本位于工程根的 readme\ 目录下。
  exit /b 1
)
if not exist "%FRONTEND_DIR%\package.json" (
  echo [错误] 未找到 frontend\package.json，请确认脚本位于工程根的 readme\ 目录下。
  exit /b 1
)

rem ---- 1) 选择 Python 解释器（优先 3.12 / 3.11）-----------------------------
set "PY_CMD="

py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.12"

if not defined PY_CMD (
  py -3.11 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=py -3.11"
)

if not defined PY_CMD (
  py -3.13 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=py -3.13"
)

if not defined PY_CMD (
  python -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
  echo [错误] 未找到可用的 Python 解释器（要求 ^>= 3.10）。
  echo        请安装 Python 3.11 或 3.12 后重试：https://www.python.org/downloads/
  exit /b 1
)

for /f "tokens=1,2" %%a in ('%PY_CMD% -c "import sys;print(sys.version_info[0],sys.version_info[1])"') do set "PY_VER=%%a.%%b"
echo [环境] 使用解释器: %PY_CMD%（Python %PY_VER%）

echo %PY_VER% | findstr /r "^3\.1[45]" >nul
if not errorlevel 1 (
  echo [警告] 检测到 Python %PY_VER%：部分依赖可能缺少预编译轮子，
  echo        安装失败时请改装 Python 3.11 / 3.12 并重建 backend\.venv（详见 readme\README.md 常见问题）。
)
echo.

rem ---- 2) 创建虚拟环境（幂等，不删除已存在内容）----------------------------
if exist "%VENV_PY%" (
  echo [1/4] [跳过] 已存在 backend\.venv（%VENV_PY%），保留现有环境不删除
) else (
  if exist "%VENV_DIR%" (
    echo [1/4] [提示] backend\.venv 已存在但缺少 Scripts\python.exe，尝试就地补建（不删除已有内容）
  ) else (
    echo [1/4] 创建虚拟环境 backend\.venv ...
  )
  %PY_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [错误] 创建虚拟环境失败，请检查 Python 安装是否完整。
    exit /b 1
  )
  if not exist "%VENV_PY%" (
    echo [错误] 未生成 %VENV_PY%，请用官方 CPython 手动创建虚拟环境。
    exit /b 1
  )
)
echo        使用 %VENV_PY%
echo.

rem ---- 3) 后端依赖 -----------------------------------------------------------
echo [2/4] 安装后端依赖（pip install -r requirements.txt）...
"%VENV_PY%" -m pip install --disable-pip-version-check --quiet --upgrade pip
if errorlevel 1 echo [提示] pip 自升级失败（离线环境可忽略），继续使用当前 pip 版本

pushd "%BACKEND_DIR%"
"%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  popd
  echo [错误] 后端依赖安装失败。
  echo        若当前为 Python 3.14，常见原因是 pydantic-core / sqlalchemy 缺少预编译轮子；
  echo        请安装 Python 3.11 或 3.12，删除 backend\.venv 后重新运行本脚本。
  exit /b 1
)
popd
echo.

rem ---- 4) 前端依赖 -----------------------------------------------------------
echo [3/4] 安装前端依赖（npm install）...
where npm >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 npm，请先安装 Node.js（^>= 18）：https://nodejs.org/
  exit /b 1
)
if exist "%FRONTEND_DIR%\node_modules" (
  echo        [跳过] 已存在 frontend\node_modules，保留现有依赖不删除
  echo        如需更新依赖，请手动执行: cd frontend ^&^& npm install
) else (
  pushd "%FRONTEND_DIR%"
  call npm install
  if errorlevel 1 (
    popd
    echo [错误] npm install 失败，请检查网络或 npm 镜像配置。
    exit /b 1
  )
  popd
)
echo.

rem ---- 5) 初始化 SQLite ------------------------------------------------------
echo [4/4] 初始化 SQLite（backend\campus.db，幂等建表）...
pushd "%BACKEND_DIR%"
"%VENV_PY%" -c "from app.db import init_db; init_db()"
if errorlevel 1 (
  popd
  echo [错误] 数据库初始化失败，请检查 backend\app\db.py 与 app\models.py 是否完整。
  exit /b 1
)
popd
echo.

rem ---- 6) 完成提示（不自动创建 .env）---------------------------------------
echo ==================================================================
echo 安装完成。脚本未自动创建 backend\.env（避免真实 Key 被误提交）。
echo.
echo 下一步：
echo   1^) 配置环境变量（二选一）：
echo      - 真实 MaaS 调用：copy backend\.env.example backend\.env
echo        然后把 MAAS_API_KEY / MAAS_BASE_URL / MAAS_MODEL 改成真实值；
echo      - 离线演示：不创建 .env，直接设置 MAAS_MOCK=1 运行（示例文件默认即为 1）。
echo.
echo   2^) 启动后端（终端 1，端口 8000，以下命令在工程根目录执行）：
echo      cd backend
echo.
echo   3^) 启动前端（终端 2，端口 5173，同上）：
echo      cd frontend
echo      npm run dev
echo.
echo   4^) 浏览器打开 http://localhost:5173 ，演示账号 teacher01 / student01
echo      （首次登录自动建号，无需密码）。
echo.
echo   健康检查：curl -s http://127.0.0.1:8000/api/health
echo ==================================================================
echo.
endlocal
exit /b 0